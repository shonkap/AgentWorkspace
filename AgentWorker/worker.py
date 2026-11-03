import os
import time
import glob
import argparse
import requests
import docker
import ollama

# ================= CONFIGURATION =================
WORKSPACE_DIR = os.path.expanduser("~/ai-agent-workspace")
QUEUE_DIR = os.path.join(WORKSPACE_DIR, "queue")
COMPLETED_DIR = os.path.join(WORKSPACE_DIR, "completed")
LOGS_DIR = os.path.join(WORKSPACE_DIR, "logs")

# Model configurations
HEAVY_MODEL = "qwen3.6-27b-uncensored"
FAST_MODEL = "qwen2.5-coder:7b"

HEAVY_HOST = "http://localhost:11434"
FAST_HOST = "http://localhost:11435"

SANDBOX_CONTAINER_NAME = "ollama-nvidia"
MAX_ITERATIONS = 10  # Generous cap for complex multi-step tasks

# Initialize Docker client
docker_client = docker.from_env()

# Ensure directories exist
os.makedirs(QUEUE_DIR, exist_ok=True)
os.makedirs(COMPLETED_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

heavy_client = ollama.Client(host=HEAVY_HOST)
fast_client = ollama.Client(host=FAST_HOST)


def search_web(query: str) -> str:
    """Performs a lightweight web search using DuckDuckGo instant answer/HTML API."""
    print(f"[Search Tool] Searching web for: '{query}'")
    try:
        url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            return f"Search failed with status code {response.status_code}"
            
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        results = []
        for a in soup.find_all('a', class_='result__snippet', limit=3):
            results.append(a.get_text())
            
        if not results:
            return "No relevant web search results found."
        return "\n--- Search Results ---\n" + "\n".join(results)
    except Exception as e:
        return f"Web search error: {str(e)}"


def run_in_sandbox(command: str) -> str:
    """Executes a bash command safely inside the isolated Docker container."""
    try:
        container = docker_client.containers.get(SANDBOX_CONTAINER_NAME)
        print(f"\n[Sandbox] Running command in container:\n{command}")
        
        # Explicitly ensure /workspace exists inside the container first
        container.exec_run(cmd=["mkdir", "-p", "/workspace"])
        
        # Run command with workdir set safely
        result = container.exec_run(
            cmd=["bash", "-c", command],
            workdir="/workspace"
        )
        
        output = result.output.decode("utf-8")
        exit_code = result.exit_code
        
        combined_output = f"Exit Code: {exit_code}\nOutput:\n{output}"
        print(f"[Sandbox Output]:\n{combined_output}")
        return combined_output

    except Exception as e:
        err_msg = f"Container execution error: {str(e)}"
        print(f"[Error] {err_msg}")
        return err_msg


def audit_code_safety(code_block: str) -> bool:
    """Sends generated code to the fast auditor model on the 1080 container."""
    print(f"[Auditor] Sending code/commands to {FAST_MODEL} on 1080 container...")
    audit_prompt = (
        "You are a strict security auditor. Analyze the following shell commands/code. "
        "Check if they contain malicious intent, destructive filesystem wipes (like rm -rf /), "
        "or severe security hazards. Reply with ONLY 'SAFE' or 'UNSAFE', followed by a short reason.\n\n"
        f"{code_block}"
    )
    try:
        response = fast_client.chat(
            model=FAST_MODEL,
            messages=[{"role": "user", "content": audit_prompt}],  # Fixed from "prompt" to "content"
            options={"temperature": 0.0}
        )
        verdict = response['message']['content'].strip().upper()
        print(f"[Auditor Verdict]: {verdict}")
        
        if "SAFE" in verdict and "UNSAFE" not in verdict:
            return True
    except Exception as e:
        print(f"[Warning] Fast model audit failed to respond: {e}")
        
    return False  # Fail-safe default


def extract_tag_content(text: str, tag: str) -> str:
    """Helper to parse custom XML-like tags from heavy model output."""
    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"
    if start_tag in text and end_tag in text:
        return text.split(start_tag)[1].split(end_tag)[0].strip()
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
                        "You are an autonomous background agent operating inside a secure Docker container (/workspace). "
                        "You can execute multi-step tasks. For each step, analyze what needs to be done. "
                        "If you need to run bash commands, enclose them in <commands>...</commands>. "
                        "If you need to search the web for documentation or answers (if enabled), enclose the query in <search>...</search>. "
                        "When you have completely finished the task and verified success, write <status>COMPLETE</status>. "
                        "If you need to continue to the next step or retry after an error, write <status>CONTINUE</status>.\n\n"
                        f"Task Goal: {initial_prompt}"
                    )
                }
            ]
            
            last_execution_output = "No commands executed yet."
            final_summary = ""
            
            while iteration < MAX_ITERATIONS and not task_success:
                iteration += 1
                print(f"\n--- Iteration {iteration} of {MAX_ITERATIONS} ---")
                
                # Feed the latest state/output back into conversation history
                feedback_msg = (
                    f"Result of previous step / execution output:\n{last_execution_output}\n\n"
                    "Determine the next action. Output <commands>...</commands> if you need to run code, "
                    "<search>...</search> if you need to look up documentation, and specify <status>CONTINUE</status> or <status>COMPLETE</status>."
                )
                conversation_history.append({"role": "user", "content": feedback_msg})
                
                # Call heavy model
                response = heavy_client.chat(model=HEAVY_MODEL, messages=conversation_history)
                model_reply = response['message']['content']
                conversation_history.append({"role": "assistant", "content": model_reply})
                
                print(f"\n[Heavy Model Reasoning & Plan]:\n{model_reply}")
                
                # Check status decided by the model
                status = extract_tag_content(model_reply, "status").upper()
                
                # 1. Check if model requested a web search (and feature is enabled)
                search_query = extract_tag_content(model_reply, "search")
                if search_query and enable_internet:
                    search_results = search_web(search_query)
                    last_execution_output = search_results
                    print(f"[Search Result Output Provided to Model]")
                    continue # Let model evaluate search results in next loop
                
                # 2. Extract and audit bash commands if requested
                commands = extract_tag_content(model_reply, "commands")
                if commands:
                    if not audit_code_safety(commands):
                        print("[❌ Blocked] Auditor flagged task as risky. Stopping task.")
                        last_execution_output = "Blocked by security auditor due to policy violation."
                        break
                    
                    # Run in container sandbox
                    last_execution_output = run_in_sandbox(commands)
                else:
                    last_execution_output = "No commands were provided in this step."
                
                # 3. Evaluate completion
                if status == "COMPLETE" or ("Exit Code: 0" in last_execution_output and not commands):
                    print(f"[✓] Task {task_name} marked COMPLETE by model.")
                    task_success = True
                    final_summary = model_reply
                    break
                elif status == "CONTINUE":
                    print("[*] Model decided to continue to next step...")
                else:
                    # Fallback default if status tag was missing
                    if "Exit Code: 0" in last_execution_output:
                        task_success = True
                        break

            # Generate clean summary log
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
        process_queue(enable_internet=args.enable_internet)
    except KeyboardInterrupt:
        print("\n[!] Worker stopped gracefully by user.")
