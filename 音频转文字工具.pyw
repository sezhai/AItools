import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import os
import sys
import json

class WhisperLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("whisper.cpp 启动器")
        
        # 窗口居中逻辑 (维持 1150x850 总大小)
        window_width = 1150
        window_height = 850
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = int((screen_width - window_width) / 2)
        y = int((screen_height - window_height) / 2)
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        self.process = None
        self.vars = {} # 统一管理所有输入变量
        
        self.meta_file = "whisper_launcher_meta.json"
        self.current_config_file = "whisper_config.json"
        self._load_meta()
        
        self.setup_ui()
        self.load_settings()

    def _load_meta(self):
        if os.path.exists(self.meta_file):
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    last_cfg = meta.get("last_config", "whisper_config.json")
                    if os.path.exists(last_cfg):
                        self.current_config_file = last_cfg
            except Exception:
                pass

    def _save_meta(self):
        try:
            with open(self.meta_file, "w", encoding="utf-8") as f:
                json.dump({"last_config": self.current_config_file}, f)
        except Exception:
            pass

    def setup_ui(self):
        # 核心布局
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.main_container.columnconfigure(0, weight=4, uniform="ratio_lock")
        self.main_container.columnconfigure(1, weight=3, uniform="ratio_lock")
        self.main_container.rowconfigure(0, weight=1)

        # 左侧面板
        self.left_frame_container = ttk.Frame(self.main_container)
        self.left_frame_container.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.canvas = tk.Canvas(self.left_frame_container, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.left_frame_container, orient="vertical", command=self.canvas.yview)
        
        self.left_frame = ttk.Frame(self.canvas)
        self.left_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        
        self.canvas_window = self.canvas.create_window((0, 0), window=self.left_frame, anchor="nw")
        
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.build_left_panel()

        # 右侧面板
        self.right_frame = ttk.Frame(self.main_container)
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 0))
        self.build_right_panel()

    def _on_mousewheel(self, event):
        if event.delta > 0:
            self.canvas.yview_scroll(-1, "units")
        elif event.delta < 0:
            self.canvas.yview_scroll(1, "units")

    # ---- 统一控件生成，自动注册到 self.vars 字典 ----
    def create_input_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=22, anchor=tk.W).pack(side=tk.LEFT)
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        ttk.Entry(frame, textvariable=var, width=20).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def create_combo_row(self, parent, label_text, values, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=22, anchor=tk.W).pack(side=tk.LEFT)
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        cb = ttk.Combobox(frame, textvariable=var, values=values, width=20)
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
    def create_check_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        var = tk.BooleanVar(value=default_val)
        self.vars[var_key] = var
        ttk.Checkbutton(frame, text=label_text, variable=var).pack(anchor=tk.W)

    def create_file_row(self, parent, label_text, default_val, var_key, filetypes):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=22, anchor=tk.W).pack(side=tk.LEFT)
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        entry = ttk.Entry(frame, textvariable=var, width=15)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        def browse_file():
            filepath = filedialog.askopenfilename(filetypes=filetypes)
            if filepath: var.set(filepath)
        ttk.Button(frame, text="浏览...", command=browse_file, width=8).pack(side=tk.LEFT)

    def create_dir_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=22, anchor=tk.W).pack(side=tk.LEFT)
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        entry = ttk.Entry(frame, textvariable=var, width=15)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        def browse_dir():
            dirpath = filedialog.askdirectory()
            if dirpath: var.set(dirpath)
        ttk.Button(frame, text="选择目录...", command=browse_dir, width=8).pack(side=tk.LEFT)

    def build_left_panel(self):
        # --- 1. 基础路径配置 ---
        g_basic = ttk.LabelFrame(self.left_frame, text="文件与路径 (必填)")
        g_basic.pack(fill=tk.X, padx=5, pady=5)
        
        self.create_dir_row(g_basic, "whisper-cli 所在目录:", ".", "whisper_dir")
        self.create_file_row(g_basic, "模型文件路径 (-m):", "models/ggml-large-v3.bin", "model", 
                             filetypes=[("GGML Model", "*.bin"), ("All files", "*.*")])
        self.create_file_row(g_basic, "输入音视频 (-f):", "", "input_file", 
                             filetypes=[("Audio/Video", "*.wav;*.mp3;*.mp4;*.mkv;*.flac;*.m4a"), ("All files", "*.*")])
        self.create_dir_row(g_basic, "输出保存目录:", "", "output_dir")
        ttk.Label(g_basic, text="* 若不选输出目录，默认保存在输入文件同级目录", foreground="gray", font=("", 8)).pack(anchor=tk.W, padx=5)

        # --- 2. 识别与语言 ---
        g_lang = ttk.LabelFrame(self.left_frame, text="识别设置")
        g_lang.pack(fill=tk.X, padx=5, pady=5)
        self.create_combo_row(g_lang, "识别语言 (-l):", ["auto", "zh", "en", "ja", "ko"], "zh", "language")
        self.create_check_row(g_lang, "直接翻译为英文 (-tr)", False, "translate")

        # --- 3. 输出格式设置 ---
        g_fmt = ttk.LabelFrame(self.left_frame, text="输出格式控制")
        g_fmt.pack(fill=tk.X, padx=5, pady=5)
        self.create_check_row(g_fmt, "生成 .srt 标准字幕 (-osrt)", True, "osrt")
        self.create_check_row(g_fmt, "生成 .txt 纯文本无时间轴 (-otxt)", False, "otxt")
        self.create_check_row(g_fmt, "生成 .vtt 网页字幕 (-ovtt)", False, "ovtt")
        self.create_check_row(g_fmt, "生成 .csv 表格 (-ocsv)", False, "ocsv")

        # --- 4. 高级过滤参数 ---
        g_adv = ttk.LabelFrame(self.left_frame, text="高级控制与幻觉过滤")
        g_adv.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_adv, "熵阈值 (-et):", "2.8", "et")
        ttk.Label(g_adv, text="* Entropy Threshold，用于过滤模型发癫/幻觉，推荐 2.4 - 2.8", foreground="gray", font=("", 8)).pack(anchor=tk.W, padx=5)
        
        self.create_input_row(g_adv, "最大上下文限制 (-mc):", "0", "mc")
        ttk.Label(g_adv, text="* 限制上下文长度。设为 0 可防长音频重复死循环", foreground="gray", font=("", 8)).pack(anchor=tk.W, padx=5)
        
        self.create_input_row(g_adv, "使用的线程数 (-t):", "4", "threads")

    def build_right_panel(self):
        # 顶部的按钮栏
        top_frame = ttk.Frame(self.right_frame)
        top_frame.pack(fill=tk.X, padx=5, pady=(10, 5))

        self.start_btn = ttk.Button(top_frame, text="▶ 开始识别", command=self.toggle_process, width=10)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 2))

        ttk.Button(top_frame, text="📂 加载配置", command=self.load_config_dialog, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="💾 保存配置", command=self.save_settings, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="📜 导出脚本", command=self.export_script, width=10).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="❓ 帮助", command=self.show_help, width=10).pack(side=tk.LEFT, padx=2)

        # 状态栏
        status_frame = ttk.Frame(self.right_frame)
        status_frame.pack(fill=tk.X, padx=5, pady=(5, 5))
        self.lbl_status = tk.Label(status_frame, text="等待就绪", fg="red", font=("Microsoft YaHei", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT)
        self.lbl_config = ttk.Label(status_frame, text=f"当前配置: {os.path.basename(self.current_config_file)}", foreground="blue")
        self.lbl_config.pack(side=tk.RIGHT)

        ttk.Separator(self.right_frame, orient='horizontal').pack(fill=tk.X, padx=5, pady=5)

        # 日志区
        ttk.Label(self.right_frame, text="控制台输出").pack(anchor=tk.W, padx=5)
        self.log_text = tk.Text(self.right_frame, bg="black", fg="white", font=("Consolas", 10), height=1)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        ttk.Button(self.right_frame, text="清空日志", command=lambda: self.log_text.delete(1.0, tk.END)).pack(anchor=tk.E, padx=5, pady=(0, 5))

    def show_help(self):
        help_win = tk.Toplevel(self.root)
        help_win.title("Whisper 参数详解与帮助")
        help_win.geometry("600x650")
        
        help_win.transient(self.root)
        help_win.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 300
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 325
        help_win.geometry(f"+{x}+{y}")

        txt = tk.Text(help_win, font=("Microsoft YaHei", 10), padx=15, pady=15, wrap=tk.WORD, bg="#f9f9f9")
        scrollbar = ttk.Scrollbar(help_win, command=txt.yview)
        txt.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        help_content = """=== Whisper.cpp 参数详细说明 ===

【基础配置】
• -m (模型文件): 必须是 whisper 的 .bin 格式权重文件。
• -f (输入文件): 支持绝大多数常见的音视频格式 (wav, mp4, mp3 等)。
• 输出保存目录: 默认情况下生成的文件会和原视频放在同一个文件夹。

【识别与语言】
• -l (语言): 默认 zh (中文)。若设为 auto，程序会自动猜测语言。
• -tr (直接翻译): 勾选后，输出强制翻译成“英文”。

【输出格式】
• -osrt (标准字幕): [最常用] 带有时间轴的 .srt 文件。
• -otxt (纯文本): 没有任何时间标记的纯文字。

【高级控制与防幻觉】
• -et (熵阈值 Entropy Threshold): [推荐值: 2.4 到 2.8] 防模型“幻觉”。
• -mc (最大上下文 Max Context): [推荐值: 0] 防无限循环复读。
• -t (线程数): 参与计算的 CPU 线程数。
"""
        txt.insert(tk.END, help_content)
        txt.config(state=tk.DISABLED)

    def load_config_dialog(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON 配置文件", "*.json"), ("所有文件", "*.*")])
        if filepath: self.load_settings(filepath)

    def save_settings(self):
        filepath = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=os.path.basename(self.current_config_file),
            filetypes=[("JSON 配置文件", "*.json"), ("所有文件", "*.*")]
        )
        if filepath:
            config_data = {k: v.get() for k, v in self.vars.items()}
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=4)
                self.current_config_file = filepath
                self.lbl_config.config(text=f"当前: {os.path.basename(filepath)}")
                self._save_meta()
                self.append_log(f"[系统] 已切换并保存配置: {os.path.basename(filepath)}\n")
            except Exception as e:
                messagebox.showerror("保存失败", f"保存失败:\n{str(e)}")

    def load_settings(self, filepath=None):
        if filepath is None: filepath = self.current_config_file
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                for k, v in config_data.items():
                    if k in self.vars: self.vars[k].set(v)
                self.current_config_file = filepath
                if hasattr(self, 'lbl_config'):
                    self.lbl_config.config(text=f"当前: {os.path.basename(filepath)}")
                self._save_meta()
            except Exception: pass

    def build_command(self):
        w_dir = self.vars.get("whisper_dir").get().strip() or "."
        
        exe_candidates = ["whisper-cli.exe", "main.exe", "whisper-cli", "main"]
        server_exe = None
        for exe_name in exe_candidates:
            full_path = os.path.join(w_dir, exe_name)
            if os.path.exists(full_path):
                server_exe = full_path
                break
                
        if not server_exe:
            server_exe = os.path.join(w_dir, "whisper-cli.exe" if os.name == 'nt' else "whisper-cli")
            
        cmd = [server_exe]
        
        input_file = self.vars["input_file"].get().strip()
        cmd.extend(["-m", self.vars["model"].get().strip()])
        cmd.extend(["-f", input_file])
        cmd.extend(["-l", self.vars["language"].get().strip()])
        
        output_dir = self.vars["output_dir"].get().strip()
        if output_dir and input_file:
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            out_prefix = os.path.join(output_dir, base_name)
            cmd.extend(["-of", out_prefix])
            
        flags = [
            ("osrt", "-osrt"), ("otxt", "-otxt"), ("ovtt", "-ovtt"), 
            ("ocsv", "-ocsv"), ("translate", "-tr")
        ]
        for key, flag in flags:
            if self.vars[key].get():
                cmd.append(flag)
                
        advanced = [("et", "-et"), ("mc", "-mc"), ("threads", "-t")]
        for key, flag in advanced:
            val = self.vars[key].get().strip()
            if val:
                cmd.extend([flag, val])
                
        return cmd

    def export_script(self):
        if not self.vars["input_file"].get().strip():
            messagebox.showwarning("警告", "请先选择一个输入音视频文件！")
            return
            
        cmd_list = self.build_command()
        safe_cmd = [f'"{item}"' if " " in item else item for item in cmd_list]

        script_content = "@echo off\nchcp 65001 > nul\ntitle Whisper CLI 独立任务\n\n"
        script_content += " ".join(safe_cmd) + "\n\npause"
        
        try:
            bat_name = f"run_whisper.bat"
            with open(bat_name, "w", encoding="utf-8") as f:
                f.write(script_content)
            messagebox.showinfo("成功", f"已在当前目录生成独立脚本：\n{bat_name}")
        except Exception as e:
            messagebox.showerror("失败", f"生成脚本失败:\n{str(e)}")

    def toggle_process(self):
        if not self.vars["input_file"].get().strip():
            messagebox.showwarning("拦截", "你必须先选择一个需要处理的音频或视频文件 (-f)！")
            return
            
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.append_log("\n[系统] 正在强行终止识别任务...")
            self.start_btn.config(text="▶ 开始识别")
            self.lbl_status.config(text="已终止", fg="red")
        else:
            self.log_text.delete(1.0, tk.END)
            self.start_process()

    def start_process(self):
        cmd = self.build_command()
        self.append_log(f"[系统] 正在执行命令:\n{' '.join(cmd)}\n")
        self.append_log("-" * 60 + "\n")

        self.start_btn.config(text="⏹ 停止识别")
        self.lbl_status.config(text="正在转写中...", fg="green")
        
        threading.Thread(target=self.run_process, args=(cmd,), daemon=True).start()

    def run_process(self, cmd):
        try:
            # 【修复点】在这里加上了 encoding='utf-8' 和 errors='replace'，防止中文字符直接把程序干崩
            self.process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            for line in self.process.stdout:
                self.root.after(0, self.append_log, line)

            self.process.wait()
            self.root.after(0, self.process_stopped)

        except FileNotFoundError:
            self.root.after(0, self.append_log, "\n[错误] 找不到 whisper-cli.exe 或 main.exe！\n请检查 'whisper-cli 所在目录' 设置是否正确。\n")
            self.root.after(0, self.process_stopped)
        except Exception as e:
            self.root.after(0, self.append_log, f"\n[错误] 发生异常: {str(e)}\n")
            self.root.after(0, self.process_stopped)

    def process_stopped(self):
        self.start_btn.config(text="▶ 开始识别")
        if self.process and self.process.returncode == 0:
            self.lbl_status.config(text="转写完成", fg="blue")
            self.append_log("\n[系统] 任务圆满完成！\n")
        else:
            self.lbl_status.config(text="异常退出", fg="red")
            self.append_log("\n[系统] 进程被中止或发生错误。\n")

    def append_log(self, text):
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = WhisperLauncherApp(root)
    root.mainloop()