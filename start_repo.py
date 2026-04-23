import os
import subprocess
import json
import requests   #    pip install python-dotenv requests
from dotenv import load_dotenv 

# 加载 .env 文件
load_dotenv()

# 从 .env 文件读取 GitHub Personal Access Token
GITHUB_USER = "buxuele"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

gitignore_content = """# 默认 .gitignore 文件，由 start_repo.py 创建
# 请编辑此文件以添加需要忽略的文件或目录
node_modules/
*.log
.env
*.pyc
__pycache__/
"""

def run_command(command):
    """运行系统命令并返回输出"""
    print(f"[执行] {command}")
    result = subprocess.run(command, shell=True, text=True, encoding="utf-8", errors="ignore")
    print(f"命令输出: {result.stdout}")
    if result.stderr:
        print(f"命令错误: {result.stderr}")
    if result.returncode != 0:
        print(f"[错误] 命令 '{command}' 失败，退出码: {result.returncode}")
        exit(1)
    return result.stdout

def check_repository_exists(repo_name):
    """检查 GitHub 仓库是否存在"""
    print(f"[检查] 仓库 '{repo_name}' 是否存在...")
    url = f"https://api.github.com/repos/{GITHUB_USER}/{repo_name}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    response = requests.get(url, headers=headers)
    print(f"[API] 响应状态码: {response.status_code}")
    
    if response.status_code == 200:
        print(f"[OK] 仓库 '{repo_name}' 已存在，将直接使用！")
        return True, response.json().get("html_url") + ".git"
    elif response.status_code == 404:
        print(f"[信息] 仓库 '{repo_name}' 不存在，将创建新仓库。")
        return False, None
    else:
        print(f"[错误] 检查仓库失败，错误信息: {response.json().get('message', '未知错误')}")
        exit(1)

def create_repository(repo_name, description):
    """通过 GitHub API 创建新仓库"""
    print(f"[创建] 新仓库 '{repo_name}'...")
    url = "https://api.github.com/user/repos"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    data = {
        "name": repo_name,
        "description": description or "",
        "private": False
    }
    response = requests.post(url, headers=headers, json=data)
    print(f"[API] 创建响应状态码: {response.status_code}")
    
    if response.status_code == 201:
        print(f"[OK] 新仓库 '{repo_name}' 创建成功！")
        return response.json().get("html_url") + ".git"
    else:
        print(f"[错误] 创建仓库失败，错误信息: {response.json().get('message', '未知错误')}")
        exit(1)

def create_gitignore():
    """创建默认 .gitignore 文件"""
    
    if not os.path.exists(".gitignore"):
        with open(".gitignore", "w", encoding="utf-8") as f:
            f.write(gitignore_content)
        print("[OK] 已创建 .gitignore 文件，请检查并编辑！")
    else:
        print("[信息] .gitignore 文件已存在，请检查是否需要修改！")

def main():
    # 检查 Token 是否有效
    if not GITHUB_TOKEN:
        print("[错误] 未在 .env 文件中找到 GITHUB_TOKEN！请确保 .env 文件存在并包含有效的 Token。")
        exit(1)

    # 获取当前文件夹名称作为默认仓库名
    default_repo_name = os.path.basename(os.getcwd())
    print(f"[信息] 默认仓库名称: {default_repo_name}")

    # 检查仓库是否存在
    repo_exists, remote_url = check_repository_exists(default_repo_name)

    # 如果仓库不存在，询问用户是否创建
    if not repo_exists:
        use_default = input(f"是否使用默认仓库名称 '{default_repo_name}'？(y/n): ").strip().lower()
        if use_default == "y":
            repo_name = default_repo_name
        else:
            repo_name = input("请输入仓库名称: ").strip()
            if not repo_name:
                print("[错误] 仓库名称不能为空！")
                exit(1)
        description = input("请输入仓库描述（可选，按回车跳过）: ").strip()
        remote_url = create_repository(repo_name, description)
    else:
        repo_name = default_repo_name

    print(f"[信息] 远程仓库地址: {remote_url}")

    # 创建 README.md
    print("[创建] README.md 文件...")
    with open("README.md", "a", encoding="utf-8") as f:
        f.write(f"# {repo_name}\n")

    # 初始化 Git 仓库
    print("[初始化] Git 仓库...")
    run_command("git init")
    run_command("git branch -M main")

    # 创建或检查 .gitignore
    create_gitignore()

    # 显示 git status 并暂停
    print("\n当前 Git 状态：")
    run_command("git status")
    input("请检查 git status 和 .gitignore 文件，编辑后按回车继续...")

    # 添加所有更改
    print("[添加] 所有更改...")
    run_command("git add .")

    # 提交更改
    commit_msg = input("请输入提交信息（默认：ok）: ").strip() or "ok"
    print(f"[提交] 使用提交信息: {commit_msg}")
    run_command(f'git commit -m "{commit_msg}"')

    # 检查是否已存在 origin
    print("[检查] 远程仓库 'origin'...")
    result = subprocess.run("git remote get-url origin", shell=True, text=True, capture_output=True, encoding="utf-8", errors="ignore")
    if result.returncode == 0:
        print("[信息] 远程仓库 'origin' 已存在，跳过添加。")
    else:
        print(f"[添加] 远程仓库: {remote_url}")
        run_command(f"git remote add origin {remote_url}")

    # 推送代码
    print("[推送] 正在推送代码到远程仓库...")
    run_command("git push -u origin main")

    # 显示最终状态
    print("\n最终 Git 状态：")
    run_command("git status")
    print("[完成] 仓库已创建并推送成功！")

if __name__ == "__main__":
    main()
