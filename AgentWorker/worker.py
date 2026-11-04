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

# 1. Global Queue, completed tasks, and logs live in ~/ai-agent-workspace
GLOBAL_WORKSPACE_DIR = os.path.expanduser("~/ai-agent-workspace")
QUEUE_DIR = os.path.join(GLOBAL_WORKSPACE_DIR, "queue")
COMPLETED_DIR = os.path.join(GLOBAL_WORKSPACE_DIR, "completed")
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

# Ensure global directories exist (queue, completed, logs)
os.makedirs(QUEUE_DIR, exist_ok=True)
os.makedirs(COMPLETED_DIR, exist_ok=True)
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
            # Bind the local workspace folder next to the script to /workspace inside the container
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
    """Strict validator that instantly blocks any path containing a space after a slash (like / workspace)."""
    print(f"[*] Fast model ({FAST_MODEL}) validating command paths and spacing...")
    
    prompt = (
        "You are a strict syntax and path validator for an autonomous agent. "
        "Review the following bash commands for path errors:\n\n"
        "CRITICAL RULE:\n"
        "1. BLOCK (INVALID) IMMEDIATELY if any path contains a space right after a slash, such as / workspace, '/ workspace/', or \"/ workspace/game.py\". "
        "Linux paths cannot have spaces after slashes. They must always be written tightly as /workspace.\n"
        "2. BLOCK (INVALID) if the agent tries to dump project files into root-level directories instead of /workspace.\n"
        "3. ALLOW clean paths that correctly use /workspace or relative paths with zero spaces after slashes.\n\n"
        "Format your reply strictly as:\n"
        "STATUS: VALID or INVALID\n"
        "REASON: (If invalid, state clearly: 'Forbidden space detected after slash. Change / workspace to /workspace.')\n\n"
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
    """Executes bash commands directly inside the container, with strict output truncation to protect context."""
    try:
        container = docker_client.containers.get(SANDBOX_CONTAINER_NAME)
        print(f"\n[Sandbox Exec]:\n{command}")
        
        # Ensure /workspace exists inside the container
        container.exec_run(cmd=["mkdir", "-p", "/workspace"])
        
        # Execute strictly inside /workspace so relative paths work automatically
        result = container.exec_run(
            cmd=["bash", "-c", command],
            workdir="/workspace"
        )
        
        output = result.output.decode("utf-8")
        exit_code = result.exit_code
        
        # CRITICAL SAFETY NET: Truncate massive outputs to prevent context window token explosions
        MAX_OUTPUT_CHARS = 4000
        if len(output) > MAX_OUTPUT_CHARS:
            output = (
                output[:MAX_OUTPUT_CHARS] + 
                f"\n\n[⚠️ WARNING: Output truncated! {len(output)} total characters generated. "
                "Avoid recursive listings like 'ls -laR' or dumping large files directly into stdout.]"
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
            task_success = False
            conversation_history = [
                {
                    "role": "user",
                    "content": (
                        "You are an autonomous background agent operating inside a secure Docker container. "
                        "**CRITICAL DIRECTORY RULE:** Your current working directory is **`/workspace`**. "
                        "All files, directories, code scripts, and projects MUST be created and executed right here in `/workspace` (or relative to it). "
                        "\n\n🚨 **CRITICAL CODING RULE (NO MONOLITHIC FILES):** "
                        "Never try to write a massive 300+ line script in a single command block, or your output will get cut off by token limits! "
                        "Build projects incrementally: Create the base file first (e.g., using `touch` or a small skeleton), "
                        "and then use python scripts or `cat << 'EOF' >> filename` to append classes, rooms, or logic step-by-step across multiple iterations. "
                        "\n\nFor each step, analyze what needs to be done. "
                        "Enclose bash commands in <commands>...</commands>, web search queries in <search>...</search>, "
                        "and write <status>COMPLETE</status> when finished or <status>CONTINUE</status> to proceed."
                        f"\n\nTask Goal: {initial_prompt}"
                    )
                }
            ]
            
            last_execution_output = "No commands executed yet."
            final_summary = ""
            
            # Open-ended loop governed by model status tags, with prompt reinforcement on every turn
            while not task_success:
                iteration += 1
                print(f"\n--- Autonomous Step {iteration} ---")
                
                feedback_msg = (
                    f"Result of previous step / execution output:\n{last_execution_output}\n\n"
                    "⚠️ REMINDER: YOUR WORKING DIRECTORY IS /workspace. "
                    "All project files, source code, and custom directories MUST be created inside /workspace (e.g., mkdir /workspace/office-game).\n\n"
                    "Determine the next action. Output <commands>...</commands> if you need to run code, "
                    "<search>...</search> if you need to look up documentation, and specify <status>CONTINUE</status> or <status>COMPLETE</status>."
                )
                conversation_history.append({"role": "user", "content": feedback_msg})
                
                response = heavy_client.chat(model=HEAVY_MODEL, messages=conversation_history)
                model_reply = response['message']['content']
                conversation_history.append({"role": "assistant", "content": model_reply})
                
                print(f"\n[Heavy Model Reasoning & Plan]:\n{model_reply}")
                
                status = extract_tag_content(model_reply, "status").upper()
                
                # 1. Check web search request
                search_query = extract_tag_content(model_reply, "search")
                if search_query and enable_internet:
                    search_results = search_web(search_query)
                    last_execution_output = search_results
                    print(f"[Search Result Output Provided to Model]")
                    continue
                
                # 2. Extract, Validate, and Audit bash commands with Feedback Loops
                commands = extract_tag_content(model_reply, "commands")
                if commands:
                    # Step A: Fast model path validator check
                    is_valid, validation_msg = validate_commands_with_fast_model(commands)
                    if not is_valid:
                        print("[❌ Path Rejected] Fast model flagged incorrect path usage.")
                        last_execution_output = validation_msg
                        continue  # Feed warning back to heavy model
                    
                    # Step B: Security auditor check (Now a soft-block feedback loop instead of a hard crash!)
                    is_safe, audit_msg = audit_code_safety(commands)
                    if not is_safe:
                        print("[❌ Auditor Blocked] Flagged as risky. Feeding reason back to heavy model.")
                        last_execution_output = audit_msg
                        continue  # Feed auditor warning back to heavy model so it can rewrite the command!
                    
                    # Step C: Execute in sandbox
                    last_execution_output = run_in_sandbox(commands)
                else:
                    last_execution_output = "No commands were provided in this step."
                
                # 3. Strict Completion Evaluation
                if status == "COMPLETE":
                    print(f"[✓] Task {task_name} marked COMPLETE by model.")
                    task_success = True
                    final_summary = model_reply
                    break
                elif status == "CONTINUE" or commands:
                    print("[*] Model decided to continue to next step...")
                else:
                    print("[*] No explicit status tag found. Continuing loop...")

            # Save log file
            log_filename = os.path.join(LOGS_DIR, f"log_{task_name}")
            with open(log_filename, "w") as log_file:
                log_file.write(
                    f"Task: {task_name}\n"
                    f"Status: {'SUCCESS' if task_success else 'COMPLETED WITH LIMITS / FAILED'}\n\n"
                    f"Final Reasoning & Output Summary:\n{final_summary or last_execution_output}"
                )
            
            print(f"🧠 Log saved to {log_filename}")
            
            # Archive task file
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