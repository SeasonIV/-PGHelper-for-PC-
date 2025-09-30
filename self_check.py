import sys
import winreg
import os
# 替换pkg_resources（解决弃用警告），用importlib.metadata检查依赖
from importlib.metadata import distributions, PackageNotFoundError

def check_vc_redist():
    """检查Microsoft Visual C++运行库是否安装"""
    redist_found = False
    paths = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    ]
    target_names = [
        "Microsoft Visual C++ 2015-2022 Redistributable",
        "Microsoft Visual C++ 2015-2019 Redistributable",
        "Microsoft Visual C++ 2015 Redistributable"
    ]
    for path in paths:
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
            num_subkeys = winreg.QueryInfoKey(key)[0]
            for i in range(num_subkeys):
                subkey_name = winreg.EnumKey(key, i)
                subkey = winreg.OpenKey(key, subkey_name)
                try:
                    display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                    for target in target_names:
                        if target in display_name:
                            print(f"✅ 找到VC++运行库: {display_name}")
                            redist_found = True
                except FileNotFoundError:
                    pass
                winreg.CloseKey(subkey)
            winreg.CloseKey(key)
        except WindowsError:
            pass
    return redist_found

def check_python_version():
    """检查Python版本是否为3.9/3.10（PyInstaller兼容性更好）"""
    major, minor, _ = sys.version_info[:3]
    compatible = (major == 3 and (minor == 9 or minor == 10))
    print(f"🐍 Python版本: {major}.{minor}.{sys.version_info[2]}")
    if compatible:
        print("✅ Python版本兼容（推荐3.9/3.10）")
    else:
        print("⚠️ 警告：Python版本可能不兼容！推荐安装3.9或3.10版本。")
    return compatible

def check_dependencies():
    """检查关键依赖包（用importlib.metadata替代pkg_resources，避免警告）"""
    required_pkgs = ["httpx", "loguru", "requests", "pyinstaller"]
    missing = []
    installed_pkgs = {pkg.metadata['Name'].lower() for pkg in distributions()}
    for pkg in required_pkgs:
        if pkg.lower() in installed_pkgs:
            print(f"✅ 依赖 {pkg} 已安装")
        else:
            missing.append(pkg)
    if missing:
        print(f"⚠️ 警告：缺少依赖包: {', '.join(missing)}！请执行 `pip install 包名` 安装。")
    else:
        print("✅ 所有关键依赖已安装")
    return not missing

def check_packaging_files():
    """检查打包所需的文件（修正变量名错误）"""
    required_files = ["token.txt", "phone_tokens.json", "pg_assistant_gui.py"]
    missing_files = []  # 原脚本这里变量名是missing_files，最后return时写错了
    for file in required_files:
        if not os.path.exists(file):
            missing_files.append(file)
    if missing_files:
        print(f"⚠️ 警告：打包所需文件缺失: {', '.join(missing_files)}！请确认文件存在。")
    else:
        print("✅ 打包所需文件均存在")
    return not missing_files  # 修正：把missing改为missing_files

if __name__ == "__main__":
    print("===== 胖乖积分助手 自检工具 =====")
    print("\n1. 检查Microsoft Visual C++运行库:")
    has_redist = check_vc_redist()
    if not has_redist:
        print("⚠️ 未找到兼容的VC++运行库！可能导致exe运行错误。")
        print("→ 解决方案：从微软官网下载安装：https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170")
    
    print("\n2. 检查Python版本:")
    check_python_version()
    
    print("\n3. 检查关键依赖包:")
    check_dependencies()
    
    print("\n4. 检查打包所需文件:")
    check_packaging_files()
    
    print("\n===== 自检完成 =====")
    print("→ 若有「⚠️ 警告」，请根据提示修复后，再尝试打包/运行exe。")