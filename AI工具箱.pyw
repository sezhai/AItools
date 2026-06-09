import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox

class ToolboxLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("AI 工具箱 - 启动面板")
        
        # =====================================================================
        # 🛠️ 【核心配置】：完美兼容 PyInstaller 打包后的路径识别
        # =====================================================================
        if getattr(sys, 'frozen', False):
            # 如果是打包成了 exe 运行，获取 exe 所在的真实物理目录
            self.base_dir = os.path.dirname(sys.executable)
        else:
            # 如果是直接通过 .py/.pyw 脚本运行，获取当前脚本的目录
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # =====================================================================
        # 🛠️ 【功能模块配置区】
        # =====================================================================
        self.tools_config = [
            {
                "name": "本地模型引擎",
                "icon": "💻", 
                "desc": "本地 AI 算力底座，支持多模型切换 (基础/视觉/Agent/知识库)",
                "script": "本地模型启动器.pyw" 
            },
            {
                "name": "文本处理工具",
                "icon": "📝",
                "desc": "支持长文本/JSON/代码去冗余、自动分卷、AI打标签",
                "script": "文本处理工具.pyw"
            },
            {
                "name": "文字提取工具",
                "icon": "📷", 
                "desc": "支持 PDF/图片 混合转录，高精度 OCR 引擎",
                "script": "文字提取工具.pyw"
            },
            {
                "name": "音频转文字工具",
                "icon": "🎤",  # 修正了特殊 Emoji 导致的间距过大问题
                "desc": "基于 Whisper 的离线语音识别，支持生成多格式字幕与纯文本",
                "script": "音频转文字工具.pyw"
            }
        ]
        # =====================================================================

        self.root.resizable(False, False)
        
        self._build_ui()
        
        # 刷新 Tkinter 状态，让系统自动计算排版后所需的真实尺寸
        self.root.update_idletasks()
        
        window_width = 520
        # 获取实际高度，补 10 像素缓冲留白给最外层白底
        window_height = self.root.winfo_reqheight() + 10
        
        # 计算居中坐标
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = int((screen_width - window_width) / 2)
        y = int((screen_height - window_height) / 2)
        
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

    def _build_ui(self):
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
            
        style.configure(
            "Tool.TButton", 
            font=("Microsoft YaHei", 10), 
            justify="left",  
            anchor="w",      
            padding=15       
        )
        
        header_frame = ttk.Frame(self.root)
        header_frame.pack(fill=tk.X, pady=(25, 20))
        
        ttk.Label(header_frame, text="🚀 AI 工具箱", font=("Microsoft YaHei", 18, "bold"), foreground="#333333").pack()
        ttk.Label(header_frame, text="请选择你需要使用的功能模块", font=("Microsoft YaHei", 10), foreground="#666666").pack(pady=(5, 0))

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=40, pady=(0, 25))

        for i, tool in enumerate(self.tools_config):
            script_path = os.path.join(self.base_dir, tool['script'])
            
            if os.path.exists(script_path):
                btn_text = f" {tool['icon']}  启动【{tool['name']}】\n       {tool['desc']}"
                btn_state = "normal"
            else:
                btn_text = f" ❌  缺失【{tool['name']}】\n       未在当前目录找到文件: {tool['script']}"
                btn_state = "disabled" 
            
            btn = ttk.Button(
                btn_frame, 
                text=btn_text, 
                style="Tool.TButton",
                state=btn_state,
                command=lambda s=tool['script']: self.launch_script(s)
            )
            
            # 如果是最后一个按钮，取消底部间距
            if i == len(self.tools_config) - 1:
                btn.pack(fill=tk.X, pady=(0, 0))
            else:
                btn.pack(fill=tk.X, pady=(0, 15))

    def launch_script(self, script_name):
        script_path = os.path.join(self.base_dir, script_name)
        
        if not os.path.exists(script_path):
            messagebox.showerror("文件丢失", f"运行失败！未找到文件：\n【{script_name}】")
            return

        try:
            if sys.platform.startswith("win"):
                if script_name.lower().endswith(('.bat', '.cmd')):
                    # 批处理文件不得不使用控制台来执行
                    subprocess.Popen(['cmd.exe', '/c', script_path], creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=self.base_dir)
                elif script_name.lower().endswith('.pyw'):
                    # 💡【核心修复】：调用 pythonw 解释器并附加 CREATE_NO_WINDOW 标志，完美实现隐形启动
                    CREATE_NO_WINDOW = 0x08000000
                    subprocess.Popen(['pythonw', script_path], creationflags=CREATE_NO_WINDOW, cwd=self.base_dir)
                else:
                    # 普通的 .py 文件依然维持原有的弹窗方式
                    subprocess.Popen(['python', script_path], creationflags=subprocess.CREATE_NEW_CONSOLE, cwd=self.base_dir)
            else:
                # 非 Windows 系统的降级兼容处理
                if script_name.lower().endswith(('.py', '.pyw')):
                    subprocess.Popen(['python', script_path], cwd=self.base_dir)
                else:
                    subprocess.Popen([script_path], cwd=self.base_dir)
                    
        except Exception as e:
            messagebox.showerror("启动异常", f"运行 {script_name} 时发生错误：\n{e}")

if __name__ == "__main__":
    root = tk.Tk()
    
    # 使用“障眼法”隐藏初始小幽灵窗口，完美居中后由 deiconify 统一展示
    root.withdraw() 
    app = ToolboxLauncher(root)
    root.deiconify() 
    
    root.mainloop()