import subprocess
import platform

def ping_host(host: str) -> bool:
    host = host.strip()
    is_windows = platform.system().lower() == "windows"
    param = "-n" if is_windows else "-c"
    command = ["ping", param, "1", host]
    print(f"Executing: {' '.join(command)}")
    try:
        result = subprocess.run(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            timeout=3,
            shell=is_windows
        )
        print(f"Return code: {result.returncode}")
        if result.returncode != 0:
            encoding = 'gbk' if is_windows else 'utf-8'
            print(f"Error: {result.stderr.decode(encoding, errors='ignore')}")
        return result.returncode == 0
    except Exception as e:
        print(f"Exception: {str(e)}")
        return False

if __name__ == "__main__":
    print(f"System: {platform.system()}")
    print(f"Ping 127.0.0.1: {ping_host('127.0.0.1')}")
    print(f"Ping google.com: {ping_host('google.com')}")
