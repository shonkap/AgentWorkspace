import os
import time
import glob
import argparse
import re
import requests
import docker
import ollama
from bs4 import BeautifulSoup

# ================= CONFIGURATION =================
# Script directory (where Dockerfile and script live)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Global Queue, completed tasks, failed tasks, and logs live in ~/ai-agent-workspace
GLOBAL_WORKSPACE_DIR = os.path.expanduser("~/ai-agent-workspace")
QUEUE_DIR = os.path.join(GLOBAL_WORKSPACE_DIR, "queue")
COMPLETED_DIR = os.path.join(GLOBAL_WORKSPACE_DIR, "completed")
FAILED_DIR = os.path.join(GLOBAL_WORKSPACE_DIR, "failed")
LOGS_DIR = os.path.join(GLOBAL_WORKSPACE_DIR, "logs")

# 2. Local workspace folder right next to script binds to /workspace in container
LOCAL_PROJECT_WORKSPACE = os.path.join(SCRIPT_DIR, "workspace")

# Docker Configuration
IMAGE_NAME = "platformio-agent-sandbox:latest"
SANDBOX_CONTAINER_NAME = "ai-sandbox"

# Model configurations
HEAVY_MODEL = "deepseek-r1:32b"
FAST_MODEL = "qwen2.5-coder:7b"

HEAVY_HOST = "http://localhost:11434"
FAST_HOST = "http://localhost:11435"

# Initialize Docker client
docker_client = docker.from_env()

# Ensure global directories exist
os.makedirs(QUEUE_DIR, exist_ok=True)
os.makedirs(COMPLETED_DIR, exist_ok=True)
os.makedirs(FAILED_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Ensure local project workspace directory exists
os.makedirs(LOCAL_PROJECT_WORKSPACE, exist_ok=True)

heavy_client = ollama.Client(host=HEAVY_HOST)
fast_client = ollama.Client(host=FAST_HOST)


def ensure_sandbox_running():
    """Ensures the sandbox container is built, running, and has the local workspace mounted."""
    print("[*] Checking sandbox container status...")
    
    try:
        container = docker_client.containers.get(SANDBOX_CONTAINER_NAME)
        if container.status != "running":
            print(f"[*] Container '{SANDBOX_CONTAINER_NAME}' is stopped. Starting it...")
            container.start()
        else:
            print(f"[✓] Container '{SANDBOX_CONTAINER_NAME}' is already running.")
        return
    except docker.errors.NotFound:
        print(f"[*] Container '{SANDBOX_CONTAINER_NAME}' not found. Creating a new one...")

    # Check/Build image if missing
    try:
        docker_client.images.get(IMAGE_NAME)
        print(f"[✓] Docker image '{IMAGE_NAME}' found locally.")
    except docker.errors.ImageNotFound:
        print(f"[*] Docker image '{IMAGE_NAME}' not found. Building from Dockerfile...")
        docker_client.images.build(
            path=SCRIPT_DIR,  # Looks for Dockerfile in script folder
            tag=IMAGE_NAME, 
            rm=True
        )
        print(f"[✓] Image '{IMAGE_NAME}' built successfully.")

    # Launch container with local project workspace mounted to /workspace
    print(f"[*] Launching container '{SANDBOX_CONTAINER_NAME}'...")
    docker_client.containers.run(
        image=IMAGE_NAME,
        name=SANDBOX_CONTAINER_NAME,
        command="tail -f /dev/null",  # Keeps container alive in background
        detach=True,
        volumes={
            os.path.abspath(LOCAL_PROJECT_WORKSPACE): {"bind": "/workspace", "mode": "rw"}
        },
        security_opt=["label:disable"]  # Bypasses SELinux volume permission blocks if present
    )
    print(f"[✓] Sandbox container '{SANDBOX_CONTAINER_NAME}' is up and ready.")


def search_web(query: str) -> str:
    """Performs a lightweight web search using DuckDuckGo instant answer/HTML API."""
    print(f"[Search Tool] Searching web for: '{query}'")
    try:
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return f"Search failed with status code {response.status_code}"
            
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        for a in soup.find_all('a', class_='result__snippet', limit=3):
            results.append(a.get_text())
            
        if not results:
            return "No relevant web search results found."
        return "\n--- Search Results ---\n" + "\n".join(results)
    except Exception as e:
        return f"Web search error: {str(e)}"


def validate_commands_with_fast_model(commands: str):
    """Strict validator that instantly blocks any path containing a space after a slash."""
    print(f"[*] Fast model ({FAST_MODEL}) validating command paths and spacing...")
    
    prompt = (
        "You are a strict syntax and path validator for an autonomous agent. "
        "Review the following bash commands for path errors:\n\n"
        "CRITICAL RULE:\n"
        "1. BLOCK (INVALID) IMMEDIATELY if any path contains a space right after a slash, such as / workspace. "
        "They must always be written tightly as /workspace.\n"
        "2. BLOCK (INVALID) if the agent tries to dump project files into root-level directories instead of /workspace.\n"
        "3. ALLOW clean paths that correctly use /workspace or relative paths with zero spaces after slashes.\n\n"
        "Format your reply strictly as:\n"
        "STATUS: VALID or INVALID\n"
        "REASON: (If invalid, state clearly why)\n\n"
        f"Commands to review:\n{commands}"
    )
    
    try:
        response = fast_client.chat(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0}
        )
        reply = response['message']['content'].strip()
        print(f"[Fast Validator Response]:\n{reply}")
        
        if "STATUS: INVALID" in reply.upper():
            reason = "Forbidden space detected after slash. You must use /workspace with no spaces."
            if "REASON:" in reply:
                reason = reply.split("REASON:")[-1].strip()
            return False, f"⚠️ PATH VALIDATION FAILED:\n{reason}"
            
        return True, "OK"
    except Exception as e:
        print(f"[Warning] Fast model validation failed, defaulting to allow: {e}")
        return True, "OK"


def audit_code_safety(code_block: str) -> tuple[bool, str]:
    """Sends generated code to the fast auditor model, returning (is_safe, reason)."""
    print(f"[Auditor] Sending code/commands to {FAST_MODEL}...")
    audit_prompt = (
        "You are a strict security auditor. Analyze the following shell commands/code. "
        "Check if they contain malicious intent, destructive filesystem wipes (like rm -rf /), "
        "or severe security hazards. Reply with ONLY 'SAFE' or 'UNSAFE', followed by a short reason.\n\n"
        f"{code_block}"
    )
    try:
        response = fast_client.chat(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": audit_prompt}],
            options={"temperature": 0.0}
        )
        verdict = response['message']['content'].strip()
        print(f"[Auditor Verdict]: {verdict}")
        
        upper_verdict = verdict.upper()
        if "SAFE" in upper_verdict and "UNSAFE" not in upper_verdict:
            return True, "SAFE"
            
        reason = verdict.replace("UNSAFE", "").replace("unsafe", "").strip(":- ")
        if not reason:
            reason = "The security auditor flagged these commands as potentially hazardous."
        return False, f"⚠️ SECURITY AUDITOR BLOCKED COMMANDS:\n{reason}\nPlease modify your command approach to be standard and safe."
    except Exception as e:
        print(f"[Warning] Fast model audit failed to respond: {e}")
        return True, "SAFE"


def run_in_sandbox(command: str) -> str:
    """Executes bash commands directly inside the container, with strict output truncation."""
    try:
        container = docker_client.containers.get(SANDBOX_CONTAINER_NAME)
        print(f"\n[Sandbox Exec]:\n{command}")
        
        container.exec_run(cmd=["mkdir", "-p", "/workspace"])
        
        result = container.exec_run(
            cmd=["bash", "-c", command],
            workdir="/workspace"
        )
        
        output = result.output.decode("utf-8")
        exit_code = result.exit_code
        
        MAX_OUTPUT_CHARS = 4000
        if len(output) > MAX_OUTPUT_CHARS:
            output = (
                output[:MAX_OUTPUT_CHARS] + 
                f"\n\n[⚠️ WARNING: Output truncated! {len(output)} total characters generated. "
                "Avoid recursive listings or dumping massive files directly into stdout.]"
            )
        
        combined_output = f"Exit Code: {exit_code}\nOutput:\n{output}"
        print(f"[Sandbox Output Length]: {len(combined_output)} chars")
        return combined_output

    except Exception as e:
        err_msg = f"Container execution error: {str(e)}"
        print(f"[Error] {err_msg}")
        return err_msg


def extract_tag_content(text: str, tag: str) -> str:
    """Helper to parse custom XML-like tags using regex."""
    match = re.search(f"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def process_queue(enable_internet: bool):
    print(f"[*] Worker started. Watching queue directory: {QUEUE_DIR}")
    print(f"[*] Internet Search Capability: {'ENABLED' if enable_internet else 'DISABLED'}")
    
    while True:
        task_files = glob.glob(os.path.join(QUEUE_DIR, "*.txt"))
        if not task_files:
            time.sleep(5)
            continue
            
        for task_path in task_files:
            task_name = os.path.basename(task_path)
            print(f"\n[+] Processing task: {task_name}")
            
            with open(task_path, "r") as f:
                initial_prompt = f.read().strip()
                
            print(f"Prompt: {initial_prompt}")
            
            iteration = 0
            absolute_max_ceiling = 60  # Absolute hard ceiling for any task
            dynamic_task_limit = 15    # Initial default budget before model reports estimate
            buffer_steps = 5           # Extra wiggle room added to model's estimate
            
            consecutive_no_command_turns = 0
            task_success = False
            previous_estimate = "N/A"  # Track estimate across turns
            
            conversation_history = [
                {
                    "role": "user",
                    "content": (
                        "You are an autonomous background agent operating inside a secure Docker container. "
                        "**CRITICAL DIRECTORY RULE:** Your current working directory is **`/workspace`**. "
                        "All files, directories, code scripts, and projects MUST be created and executed right here in `/workspace`. "
                        "\n\n🚨 **CRITICAL CODING RULE (NO MONOLITHIC FILES):** "
                        "Never try to write a massive 300+ line script in a single command block! Build incrementally across steps. "
                        "\n\nFor each step, enclose bash commands in <commands>...</commands>, web search queries in <search>...</search>, "
                        "your estimated remaining steps in <estimated_steps>X</estimated_steps> (where X is a number that decreases as you make progress), "
                        "and write <status>COMPLETE</status> when finished or <status>CONTINUE</status> to proceed."
                        f"\n\nTask Goal: {initial_prompt}"
                    )
                }
            ]
            
            last_execution_output = "No commands executed yet."
            final_summary = ""
            
            while not task_success:
                iteration += 1
                print(f"\n--- Autonomous Step {iteration} (Dynamic Limit: {dynamic_task_limit} | Absolute Ceiling: {absolute_max_ceiling}) ---")
                
                # Hybrid budget enforcement: check against dynamic estimate limit
                if iteration > dynamic_task_limit:
                    print(f"[!] Task {task_name} exceeded dynamic estimate limit (Hit step {iteration}, budget was {dynamic_task_limit}). Moving to failed folder.")
                    
                    log_filename = os.path.join(LOGS_DIR, f"failed_{task_name}.log")
                    with open(log_filename, "w") as log_file:
                        log_file.write(f"Task {task_name} exceeded dynamic limit at iteration {iteration}.\nLast Output:\n{last_execution_output}")
                        
                    os.rename(task_path, os.path.join(FAILED_DIR, task_name))
                    break
                
                feedback_msg = (
                    f"Result of previous step / execution output:\n{last_execution_output}\n\n"
                    f"⚠️ TIMELINE TRACKER: In your last step, you estimated **{previous_estimate}** steps remaining. "
                    "Make sure your new <estimated_steps> count reflects a realistic countdown as you get closer to completion.\n\n"
                    "⚠️ REMINDER: YOUR WORKING DIRECTORY IS /workspace.\n"
                    "Determine the next action. Output <commands>...</commands>, <search>...</search>, "
                    "your updated estimated remaining steps in <estimated_steps>X</estimated_steps>, "
                    "and specify <status>CONTINUE</status> or <status>COMPLETE</status>."
                )
                conversation_history.append({"role": "user", "content": feedback_msg})
                
                response = heavy_client.chat(model=HEAVY_MODEL, messages=conversation_history)
                model_reply = response['message']['content']
                conversation_history.append({"role": "assistant", "content": model_reply})
                
                print(f"\n[Heavy Model Reasoning & Plan]:\n{model_reply}")
                
                status = extract_tag_content(model_reply, "status").upper()
                
                # Parse estimate and dynamically update the hybrid budget
                est_steps_str = extract_tag_content(model_reply, "estimated_steps")
                if est_steps_str.isdigit():
                    remaining_estimate = int(est_steps_str)
                    previous_estimate = est_steps_str
                    
                    # Hybrid calculation: current iteration + remaining estimate + buffer, capped by absolute ceiling
                    dynamic_task_limit = min(iteration + remaining_estimate + buffer_steps, absolute_max_ceiling)
                    print(f"[*] Model updated estimate: {remaining_estimate} remaining. New dynamic budget limit: step {dynamic_task_limit}")
                
                search_query = extract_tag_content(model_reply, "search")
                if search_query and enable_internet:
                    search_results = search_web(search_query)
                    last_execution_output = search_results
                    consecutive_no_command_turns = 0
                    continue
                
                commands = extract_tag_content(model_reply, "commands")
                if commands:
                    consecutive_no_command_turns = 0
                    
                    is_valid, validation_msg = validate_commands_with_fast_model(commands)
                    if not is_valid:
                        print("[❌ Path Rejected] Fast model flagged incorrect path usage.")
                        last_execution_output = validation_msg
                        continue
                    
                    is_safe, audit_msg = audit_code_safety(commands)
                    if not is_safe:
                        print("[❌ Auditor Blocked] Flagged as risky. Feeding reason back to model.")
                        last_execution_output = audit_msg
                        continue
                    
                    last_execution_output = run_in_sandbox(commands)
                else:
                    consecutive_no_command_turns += 1
                    last_execution_output = "No commands were provided in this step."
                    
                    if consecutive_no_command_turns >= 3 and status != "COMPLETE":
                        print("[*] Model is reasoning without executing commands. Injecting nudge...")
                        conversation_history.append({
                            "role": "user",
                            "content": "⚠️ You have spent several turns discussing without running commands. Please write your next actions in <commands>...</commands> or finalize with <status>COMPLETE</status>."
                        })
                        consecutive_no_command_turns = 0
                
                if status == "COMPLETE":
                    print(f"[✓] Task {task_name} marked COMPLETE by model.")
                    task_success = True
                    final_summary = model_reply
                    break
                elif status == "CONTINUE" or commands:
                    print("[*] Model decided to continue to next step...")
                else:
                    print("[*] No explicit status tag found. Continuing loop...")

            if task_success:
                log_filename = os.path.join(LOGS_DIR, f"log_{task_name}")
                with open(log_filename, "w") as log_file:
                    log_file.write(
                        f"Task: {task_name}\nStatus: SUCCESS\n\n"
                        f"Final Reasoning & Output Summary:\n{final_summary or last_execution_output}"
                    )
                print(f"🧠 Log saved to {log_filename}")
                
                completed_path = os.path.join(COMPLETED_DIR, task_name)
                os.rename(task_path, completed_path)
                print(f"[✓] Task {task_name} archived.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous Agent Background Worker")
    parser.add_argument(
        "--enable-internet", 
        action="store_true", 
        help="Allow the heavy model to perform live web searches during task execution."
    )
    args = parser.parse_args()
    
    try:
        ensure_sandbox_running()
        process_queue(enable_internet=args.enable_internet)
    except KeyboardInterrupt:
        print("\n[!] Worker stopped gracefully by user.")