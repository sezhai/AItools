import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import os
import sys
import json
import webbrowser

class LlamaLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("llama.cpp 启动器")
        
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
        
        # 记录系统元数据（用于记忆最后一次使用的配置）
        self.meta_file = "launcher_meta.json"
        self.current_config_file = "llama_config.json"
        self._load_meta() # 启动时先读取记忆
        
        self.setup_ui()
        self.load_settings() # 随后加载记忆中的配置文件

    def _load_meta(self):
        """读取程序上次关闭前的记忆（最后使用的配置文件）"""
        if os.path.exists(self.meta_file):
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    last_cfg = meta.get("last_config", "llama_config.json")
                    # 确保最后使用的文件仍然存在
                    if os.path.exists(last_cfg):
                        self.current_config_file = last_cfg
            except:
                pass

    def _save_meta(self):
        """保存当前正在使用的配置文件路径到记忆中"""
        try:
            with open(self.meta_file, "w", encoding="utf-8") as f:
                json.dump({"last_config": self.current_config_file}, f)
        except:
            pass

    def setup_ui(self):
        # ====== 核心修复：禁用 Combobox 的默认滚轮事件，防止误触 ======
        # 这会让滚轮事件直接穿透下拉框，交给底层的画布进行纯粹的上下滚动
        self.root.unbind_class("TCombobox", "<MouseWheel>")
        self.root.unbind_class("TCombobox", "<Button-4>")
        self.root.unbind_class("TCombobox", "<Button-5>")

        # ====== 布局搭建：Frame + grid 布局 ======
        # 利用 uniform 属性彻底无视内容宽度，死死锁住 1:1 比例
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.main_container.columnconfigure(0, weight=1, uniform="ratio_lock") # 左侧严格权重 1
        self.main_container.columnconfigure(1, weight=1, uniform="ratio_lock") # 右侧严格权重 1
        self.main_container.rowconfigure(0, weight=1)

        # ====== 左侧：参数设置区 ======
        self.left_frame_container = ttk.Frame(self.main_container)
        self.left_frame_container.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.canvas = tk.Canvas(self.left_frame_container, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.left_frame_container, orient="vertical", command=self.canvas.yview)
        
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

        self.left_frame = ttk.Frame(self.canvas)
        self.left_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.left_frame, anchor="nw")
        
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.build_left_panel()

        # ====== 右侧：控制与日志区 ======
        self.right_frame = ttk.Frame(self.main_container)
        self.right_frame.grid(row=0, column=1, sticky="nsew", padx=(2, 0))
        
        self.build_right_panel()

    def _on_mousewheel(self, event):
        if event.num == 4 or event.delta > 0:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or event.delta < 0:
            self.canvas.yview_scroll(1, "units")

    # ---- 统一控件生成，自动注册到 self.vars 字典 ----
    # 保持最佳视觉间距
    def create_input_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=31, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        ttk.Entry(frame, textvariable=var, width=20).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def create_combo_row(self, parent, label_text, values, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=31, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
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

    def create_file_row(self, parent, label_text, default_val, var_key, filetypes=(("All files", "*.*"),)):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=31, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        
        entry = ttk.Entry(frame, textvariable=var, width=15)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_file():
            filepath = filedialog.askopenfilename(filetypes=filetypes)
            if filepath:
                var.set(filepath)
                
        ttk.Button(frame, text="浏览...", command=browse_file, width=8).pack(side=tk.LEFT)

    def create_dir_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=31, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        
        entry = ttk.Entry(frame, textvariable=var, width=15)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_dir():
            dirpath = filedialog.askdirectory()
            if dirpath:
                var.set(dirpath)
                
        ttk.Button(frame, text="选择目录...", command=browse_dir, width=8).pack(side=tk.LEFT)

    def build_left_panel(self):
        # --- 1. 基础设置 ---
        g_basic = ttk.LabelFrame(self.left_frame, text="基础设置 (必填)")
        g_basic.pack(fill=tk.X, padx=5, pady=5)
        
        self.create_dir_row(g_basic, "llama.cpp 所在目录:", ".", "llama_dir")
        
        self.create_file_row(g_basic, "模型路径 (-m):", "", "model", 
                             filetypes=[("GGUF Model", "*.gguf"), ("All files", "*.*")])
                             
        self.create_file_row(g_basic, "多模态投影文件 (--mmproj):", "", "mmproj", 
                             filetypes=[("GGUF Projector", "*.gguf"), ("All files", "*.*")])
        
        self.create_input_row(g_basic, "监听地址 (--host):", "127.0.0.1", "host")
        self.create_input_row(g_basic, "监听端口 (--port):", "8080", "port")

        # --- 2. 模型参数 ---
        g_model = ttk.LabelFrame(self.left_frame, text="模型参数")
        g_model.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_model, "上下文长度 (-c, --ctx-size):", "32768", "ctx")
        self.create_input_row(g_model, "图像最小Tokens (--image-min-tokens):", "", "image_min_tokens")
        self.create_input_row(g_model, "GPU加速层数 (-ngl):", "", "ngl")
        self.create_input_row(g_model, "批处理大小 (-b):", "768", "b")
        self.create_input_row(g_model, "物理批处理大小 (-ub):", "512", "ub")

        # --- 3. 推理/思考模式 ---
        g_reason = ttk.LabelFrame(self.left_frame, text="推理/思考模式")
        g_reason.pack(fill=tk.X, padx=5, pady=5)
        self.create_combo_row(g_reason, "推理模式 (--reasoning):", ["", "on", "off"], "off", "reasoning")
        self.create_input_row(g_reason, "思考预算 (--reasoning-budget):", "", "reasoning_budget")
        self.create_combo_row(g_reason, "思考格式 (--reasoning-format):", ["", "none", "deepseek", "deepseek-legacy"], "", "reasoning_format")
        self.create_input_row(g_reason, "思考预算耗尽消息:", "", "reasoning_exhausted")

        # --- 4. 性能与内存 ---
        g_perf = ttk.LabelFrame(self.left_frame, text="性能与内存")
        g_perf.pack(fill=tk.X, padx=5, pady=5)
        self.create_combo_row(g_perf, "Flash Attention (-fa):", ["", "on", "off"], "on", "fa")
        self.create_combo_row(g_perf, "KV Cache 类型 K (-ctk):", ["", "q8_0", "f16", "q4_0", "q4_1"], "q8_0", "ctk")
        self.create_combo_row(g_perf, "KV Cache 类型 V (-ctv):", ["", "q8_0", "f16", "q4_0", "q4_1"], "f16", "ctv")
        self.create_check_row(g_perf, "禁用 mmap (--no-mmap)", False, "no_mmap")
        self.create_check_row(g_perf, "锁定内存 (--mlock)", False, "mlock")
        self.create_input_row(g_perf, "缓存 RAM 限制 (--cache-ram):", "1024", "cache_ram")
        self.create_input_row(g_perf, "上下文检查点 (--ctx-checkpoints):", "16", "ctx_checkpoints")

        # --- 5. 请求控制与模板 ---
        g_req = ttk.LabelFrame(self.left_frame, text="请求控制与模板")
        g_req.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_req, "并发槽位数 (-np, --n-parallel):", "1", "np")
        self.create_input_row(g_req, "保留初始Tokens (--keep):", "-1", "keep")
        self.create_check_row(g_req, "启用向量嵌入 (--embedding)", False, "embedding")
        self.create_check_row(g_req, "启用重排序 (--reranking)", False, "reranking")
        self.create_check_row(g_req, "使用 Jinja 模板 (--jinja)", True, "jinja")
        self.create_input_row(g_req, "对话模板 (--chat-template-kwargs):", "", "kwargs")

        # --- 6. 采样设置 ---
        g_sample = ttk.LabelFrame(self.left_frame, text="采样设置")
        g_sample.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_sample, "最大生成数 (-n, --n-predict):", "4096", "n_predict")
        self.create_input_row(g_sample, "温度 (--temp):", "", "temp")
        self.create_input_row(g_sample, "Top-K采样 (--top-k):", "", "top_k")
        self.create_input_row(g_sample, "Top-P采样 (--top-p):", "", "top_p")
        self.create_input_row(g_sample, "最小概率 (--min-p):", "", "min_p")
        self.create_input_row(g_sample, "存在惩罚 (--presence-penalty):", "", "presence_penalty")

        # --- 7. 高级采样 ---
        g_adv = ttk.LabelFrame(self.left_frame, text="高级采样")
        g_adv.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_adv, "重复惩罚 (--repeat-penalty):", "", "repeat_penalty")
        self.create_input_row(g_adv, "重复惩罚范围 (--repeat-last-n):", "", "repeat_last_n")
        self.create_input_row(g_adv, "随机种子 (-s, --seed):", "", "seed")

    def build_right_panel(self):
        # ====== 顶部控制与配置栏 (单行平铺) ======
        top_frame = ttk.Frame(self.right_frame)
        top_frame.pack(fill=tk.X, padx=5, pady=(10, 5))
        
        self.start_btn = ttk.Button(top_frame, text="▶ 启动服务器", command=self.toggle_server)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 2))

        ttk.Button(top_frame, text="📂 加载配置", command=self.load_config_dialog).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="💾 保存配置", command=self.save_settings).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="📜 导出BAT脚本", command=self.export_script).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="🌐 打开WebUI", command=self.open_webui).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="❓ 帮助", command=self.open_help_doc).pack(side=tk.LEFT, padx=2)

        # ====== 服务器状态区 ======
        status_header_frame = ttk.Frame(self.right_frame)
        status_header_frame.pack(fill=tk.X, padx=5, pady=(10, 0))
        
        ttk.Label(status_header_frame, text="服务器状态").pack(side=tk.LEFT)
        self.lbl_config = ttk.Label(status_header_frame, text=f"当前配置: {os.path.basename(self.current_config_file)}", foreground="blue")
        self.lbl_config.pack(side=tk.RIGHT)

        self.lbl_status = tk.Label(self.right_frame, text="未运行", fg="red", font=("Microsoft YaHei", 10, "bold"))
        self.lbl_status.pack(anchor=tk.W, padx=5, pady=(0, 5))
        
        ttk.Separator(self.right_frame, orient='horizontal').pack(fill=tk.X, padx=5, pady=2)

        # ====== 进程信息区 ======
        ttk.Label(self.right_frame, text="进程信息").pack(anchor=tk.W, padx=5, pady=(5, 0))
        
        self.lbl_run_status = ttk.Label(self.right_frame, text="运行状态: 否")
        self.lbl_run_status.pack(anchor=tk.W, padx=5, pady=2)
        
        self.lbl_pid = ttk.Label(self.right_frame, text="PID: -")
        self.lbl_pid.pack(anchor=tk.W, padx=5, pady=(0, 5))
        
        ttk.Separator(self.right_frame, orient='horizontal').pack(fill=tk.X, padx=5, pady=2)

        # ====== 日志输出区 ======
        ttk.Label(self.right_frame, text="日志输出").pack(anchor=tk.W, padx=5, pady=(5, 0))
        
        self.log_text = tk.Text(self.right_frame, bg="black", fg="white", font=("Consolas", 10), width=1)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        bottom_frame = ttk.Frame(self.right_frame)
        bottom_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bottom_frame, text="清空日志", command=lambda: self.log_text.delete(1.0, tk.END)).pack(side=tk.LEFT)

    # ====== 功能逻辑区 ======
    
    def open_help_doc(self):
        """以内部窗口的形式弹出帮助文档"""
        help_win = tk.Toplevel(self.root)
        help_win.title("llama.cpp 启动器参数详解与帮助")
        help_win.geometry("650x700")
        
        # 使弹窗居中且保持在主窗口前
        help_win.transient(self.root)
        help_win.grab_set()
        
        # 居中计算
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 325
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 350
        help_win.geometry(f"+{x}+{y}")

        # 文本框与滚动条
        txt = tk.Text(help_win, font=("Microsoft YaHei", 10), padx=15, pady=15, wrap=tk.WORD, bg="#f9f9f9")
        scrollbar = ttk.Scrollbar(help_win, command=txt.yview)
        txt.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        help_content = """=== llama.cpp 启动器 使用指南 ===

1. 基础设置 (必填)
这些是启动服务器所需的最核心参数，配置错误将直接导致服务器无法启动。

llama.cpp 所在目录
说明： 存放 llama.exe、llama-server.exe（Windows）或 llama-server（Linux/Mac）的核心程序文件夹。
建议： 点击“选择目录...”按钮，直接定位到你的工具包解压路径。

模型路径 (-m)
说明： 大语言模型文件的绝对路径，文件格式必须为 .gguf。
建议： 必填项。为了避免路径中含有特殊字符引发报错，建议存放在纯英文路径下。

多模态投影文件 (--mmproj)
说明： 用于视觉多模态模型（如 LLaVA、Qwen-VL）的视觉投射权重文件。
建议： 如果你运行的是纯文本模型，请保持为空；如果是多模态（看图说话）模型，则必须配置此项。

监听地址 (--host)
说明： 服务器绑定的网络 IP 地址。
建议： * 填 127.0.0.1：仅允许你当前的这台电脑自己访问。
填 0.0.0.0：允许局域网内的其他设备（如手机、其他电脑）通过你的 IP 地址进行访问。

监听端口 (--port)
说明： 服务开放的网页和 API 端口号。
建议： 默认 8080。如果遇到端口冲突，可以修改为 8081 或 9000 等。

2. 模型参数
负责控制模型加载时的硬件分配与核心计算规模。

上下文长度 (-c, --ctx-size)
说明： 模型能记住的上下文总长度（包含“你的问题”+“模型的回答”的总 Token 数）。
建议： 默认 32768。如果显存不足导致报错，可以适当调小（如 8192 或 4096）。

图像最小 Token 数 (--image-min-tokens)
说明： 多模态视觉模型专属参数。限制在图像编码、分块处理时生成的最小 Token 数量。
建议： 仅在配置了多模态投影文件时有效。它与上下文长度高度关联。调大此项，模型会保留更多图像细节，但会显著增加显存（VRAM）与上下文空间的占用。在 12GB 等常见显存规格下，建议先留空使用默认值。

GPU 加速层数 (-ngl)
说明： 卸载到显卡（GPU）中计算的模型层数。
建议： 最核心的加速参数。如果你的显存足够大，建议直接填入 99（代表将所有层全塞入显存），此时速度最快。如果显卡爆显存，再逐步调小该数值。

批处理大小 (-b)
说明： 逻辑批处理大小，用于控制提示词（Prompt）吞吐。
建议： 默认 768 或 2048。数值越大，处理长文本提示词的速度越快，但会占用更多显存。

物理批处理大小 (-ub)
说明： 实际交付给硬件的物理批处理大小。
建议： 默认 512。该数值必须小于或等于上面的“批处理大小 (-b)”。

3. 推理/思考模式
专门针对主流的推理型大模型（如 DeepSeek-R1、O1 等带有思考过程的模型）设计的优化选项。

推理模式 (--reasoning)
说明： 是否激活大模型的深度思考（Reasoning）链。
建议： 运行传统模型（如 Llama-3、Qwen-2.5）选择 off 或留空；运行推理模型（如 DeepSeek-R1）时选择 on。

思考预算 (--reasoning-budget)
说明： 限制模型在回答前，最多可以生成多少个“思考 Token”。
建议： 留空表示不限制，由模型自行决定何时思考结束。

思考格式 (--reasoning-format)
说明： 思考文本输出的封装格式。
建议： 针对 DeepSeek 模型，选择 deepseek 能够让前端网页完美识别并折叠 <think> 标签。

4. 性能与内存
用于极限压榨硬件性能，或在低配设备上通过降低精度挽救显存。

Flash Attention (-fa)
说明： 闪烁注意力机制。一种极其高效的算法优化。
建议： 强烈建议选择 on。它能在几乎不损失精度的前提下，大幅降低长文本下的显存占用，并提升生成速度。

KV Cache 类型 K (-ctk) 与 类型 V (-ctv)
说明： 上下文缓存（Key / Value）的键值对量化数据类型。
建议： * 追求速度和省显存：推荐将 K 缓存设为 q8_0，V 缓存设为 f16（或者两者都设为 q4_0）。
这能在损失极微小精度的情况下，释放出几个 GB 的宝贵显存。

禁用 mmap (--no-mmap)
说明： 勾选后将放弃内存映射，转而把整个模型强行一次性完整加载进内存/显存。
建议： 机械硬盘用户或经常遇到运行中卡顿的用户建议勾选，这样虽然启动慢，但运行期间不会因为频繁读取硬盘而卡顿。

锁定内存 (--mlock)
说明： 强行将模型锁定在物理内存中，禁止操作系统将其交换到虚拟内存（硬盘垃圾文件）中。
建议： 内存非常充沛的电脑可以勾选，防止模型因闲置而被系统“挂起”导致再次对话时极慢。

缓存 RAM 限制 与 上下文检查点
说明： 进阶的内存控制单元，主要用于在超长上下文处理时，限制缓存占用的内存上限。

5. 请求控制与模板
并发槽位数 (-np, --n-parallel)
说明： 允许同时处理的并发请求（用户）数量。
建议： 个人单机使用填写 1。如果是部署在服务器上供团队多人同时使用，可根据硬件能力调大（如 4 或 8）。

保留初始 Tokens (--keep)
说明： 当对话长度超过“上下文长度”导致模型必须遗忘旧内容时，此参数决定强制保留最初的多少个 Token。
建议： 默认并强烈建议设为 -1。这代表永远保留并锁死“系统提示词（System Prompt）”，防止模型在长篇对话后突然忘记自己扮演的角色或核心规则。

启用向量嵌入 (--embedding)
说明： 开启后，服务器将开放专门的 `/v1/embeddings` 端点，允许外部系统将文本转换为可检索的数学向量。
建议： 当你需要外接知识库系统（如 Dify, AnythingLLM, FastGPT）进行本地文档搜索时勾选。若仅做常规对话，保持关闭。

启用重排序 (--reranking)
说明： 开启后，服务器将支持 `/v1/rerank` 接口，可以对知识库检索出的文档片段进行二次高精度相关性打分。
建议： 仅在你加载了专属的重排序模型（如 bge-reranker）时才需开启。普通生成类模型开启无效。

使用 Jinja 模板 (--jinja)
说明： 启用现代标准的 Jinja2 提示词模板解析。
建议： 默认勾选。这能保证现在绝大多数新模型（如 Llama 3、Qwen）的角色扮演和对话格式不会错乱。

对话模板参数 (--chat-template-kwargs)
说明： 传递给 Jinja 模板的自定义高级参数字符串（Json 格式）。通常留空。

6. 采样设置
这些参数决定了模型的“性格”——是严谨死板，还是天马行空。

最大生成数 (-n, --n-predict)
说明： 限制模型单次回答输出的最大 Token 数量。
建议： 默认 4096。防止模型陷入死循环或者长篇大论停不下来。

温度 (--temp)
说明： 随机性（创造力）系数。
建议： * 数值越低（如 0.1 - 0.3）：回答极度严谨、死板、适合写代码、做数学题。
数值越高（如 0.7 - 1.0）：回答富有创造力、词汇丰富，适合写小说、文案策划。

Top-K采样 / Top-P采样 / 最小概率 (--min-p)
说明： 用于筛选概率最高的一批词汇，剔除那些胡言乱语的低概率词。
建议： 现代模型推荐重点微调 --min-p（如设定为 0.05），它比传统的 Top-P 过滤错词的效果要更优秀、更自然。

存在惩罚 (--presence-penalty)
说明： 针对“是否出现过”的词进行惩罚。数值越高，模型越倾向于谈论全新的话题。

7. 高级采样

重复惩罚 (--repeat-penalty)
说明： 针对“频繁重复使用”的词或句子进行惩罚。
建议： 默认留空。如果你发现模型陷入了“车轱辘话”复读机状态，可以将其设置为 1.1 或 1.2 予以遏制。

重复惩罚范围 (--repeat-last-n)
说明： 指定惩罚时往回倒查多少个 Token。默认留空（通常为 64）。

随机种子 (-s, --seed)
说明： 随机数发生器的种子。
建议： 默认留空（每次对话回答都不同）。如果填写一个固定数字（如 42），在相同输入和相同温度下，模型每次生成的回答将完全一模一样（常用于Debug测试）。
"""
        txt.insert(tk.END, help_content)
        txt.config(state=tk.DISABLED)

    def open_webui(self):
        host = self.vars.get("host").get().strip() or "127.0.0.1"
        port = self.vars.get("port").get().strip() or "8080"
        
        if host == "0.0.0.0":
            host = "127.0.0.1"
            
        url = f"http://{host}:{port}"
        try:
            webbrowser.open(url)
            self.append_log(f"\n[系统] 正在浏览器中尝试打开 WebUI: {url}\n")
        except Exception as e:
            self.append_log(f"\n[错误] 无法打开浏览器: {str(e)}\n")

    def update_process_info(self, is_running, pid="-"):
        if is_running:
            self.lbl_run_status.config(text="运行状态: 是")
            self.lbl_pid.config(text=f"PID: {pid}")
        else:
            self.lbl_run_status.config(text="运行状态: 否")
            self.lbl_pid.config(text="PID: -")

    def load_config_dialog(self):
        filepath = filedialog.askopenfilename(
            title="加载配置文件",
            filetypes=[("JSON 配置文件", "*.json"), ("所有文件", "*.*")]
        )
        if filepath:
            self.load_settings(filepath)

    def save_settings(self):
        filepath = filedialog.asksaveasfilename(
            title="保存配置文件",
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
                self.lbl_config.config(text=f"当前配置: {os.path.basename(filepath)}")
                self._save_meta()
                
                messagebox.showinfo("成功", f"配置已成功保存至：\n{os.path.basename(filepath)}")
                self.append_log(f"[系统] 已切换并保存配置: {os.path.basename(filepath)}\n")
            except Exception as e:
                messagebox.showerror("保存失败", f"保存配置文件失败:\n{str(e)}")

    def load_settings(self, filepath=None):
        if filepath is None:
            filepath = self.current_config_file

        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                for k, v in config_data.items():
                    if k in self.vars:
                        if k == "reasoning" and v == "":
                            v = "off"
                        if k == "reasoning_format" and v not in ["", "none", "deepseek", "deepseek-legacy"]:
                            v = ""
                        self.vars[k].set(v)
                
                self.current_config_file = filepath
                if hasattr(self, 'lbl_config'):
                    self.lbl_config.config(text=f"当前配置: {os.path.basename(filepath)}")
                self._save_meta()
                
                if hasattr(self, 'append_log'):
                    self.append_log(f"[系统] 已加载配置: {os.path.basename(filepath)}\n")
            except Exception as e:
                if hasattr(self, 'append_log'):
                    self.append_log(f"[系统] 读取配置文件失败: {str(e)}\n")

    def build_command(self):
        llama_dir = self.vars.get("llama_dir").get().strip()
        if not llama_dir:
            llama_dir = "."
            
        exe_candidates = [
            ("llama.exe", True),         
            ("llama-server.exe", False), 
            ("llama", True),             
            ("llama-server", False)      
        ]
        
        server_exe = None
        is_unified = False
        
        for exe_name, unified in exe_candidates:
            full_path = os.path.join(llama_dir, exe_name)
            if os.path.exists(full_path):
                server_exe = full_path
                is_unified = unified
                break
                
        if not server_exe:
            server_exe = os.path.join(llama_dir, "llama-server.exe" if os.name == 'nt' else "llama-server")
            
        cmd = [server_exe]
        
        if is_unified:
            cmd.append("server")
        
        mappings = [
            ("model", "-m", False),
            ("mmproj", "--mmproj", False),
            ("image_min_tokens", "--image-min-tokens", False),
            ("host", "--host", False),
            ("port", "--port", False),
            ("ctx", "-c", False),
            ("fa", "-fa", False),
            ("ctk", "-ctk", False),
            ("ctv", "-ctv", False),
            ("ngl", "-ngl", False),
            ("b", "-b", False),
            ("ub", "-ub", False),
            ("np", "-np", False),
            ("keep", "--keep", False),
            ("embedding", "--embedding", True),
            ("reranking", "--reranking", True),
            ("no_mmap", "--no-mmap", True),
            ("mlock", "--mlock", True),
            ("cache_ram", "--cache-ram", False),
            ("ctx_checkpoints", "--ctx-checkpoints", False),
            ("reasoning", "--reasoning", False),
            ("reasoning_budget", "--reasoning-budget", False),
            ("reasoning_format", "--reasoning-format", False),
            ("jinja", "--jinja", True),
            ("n_predict", "-n", False),
            ("temp", "--temp", False),
            ("top_k", "--top-k", False),
            ("top_p", "--top-p", False),
            ("min_p", "--min-p", False),
            ("presence_penalty", "--presence-penalty", False),
            ("repeat_penalty", "--repeat-penalty", False),
            ("repeat_last_n", "--repeat-last-n", False),
            ("seed", "-s", False),
            ("kwargs", "--chat-template-kwargs", False)
        ]

        for var_key, flag, is_boolean in mappings:
            if var_key not in self.vars: continue
            
            val = self.vars[var_key].get()
            if is_boolean:
                if val:  
                    cmd.append(flag)
            else:
                if isinstance(val, str) and val.strip():
                    cmd.extend([flag, val.strip()])
                    
        return cmd

    def export_script(self):
        cmd_list = self.build_command()
        
        safe_cmd = []
        for item in cmd_list:
            if " " in item or "{" in item:
                if "{" in item:
                    safe_cmd.append(f"'{item}'") 
                else:
                    safe_cmd.append(f'"{item}"')
            else:
                safe_cmd.append(item)

        script_content = "@echo off\nchcp 65001 > nul\ntitle Llama Server 独立脚本\n\n"
        script_content += " ".join(safe_cmd) + "\n\npause"
        
        try:
            base_name = os.path.splitext(os.path.basename(self.current_config_file))[0]
            bat_name = f"start_server_{base_name}.bat"
            
            with open(bat_name, "w", encoding="utf-8") as f:
                f.write(script_content)
            messagebox.showinfo("成功", f"已在当前目录生成独立启动脚本：\n{bat_name}")
        except Exception as e:
            messagebox.showerror("失败", f"生成脚本失败:\n{str(e)}")

    def toggle_server(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.append_log("\n[系统] 正在终止服务器进程...")
            self.start_btn.config(text="▶ 启动服务器")
            self.lbl_status.config(text="未运行", fg="red")
            self.update_process_info(False)
        else:
            self.log_text.delete(1.0, tk.END)
            self.start_server()

    def start_server(self):
        cmd = self.build_command()

        self.append_log(f"[系统] 正在执行后台命令:\n{' '.join(cmd)}\n")
        self.append_log("-" * 60 + "\n")

        self.start_btn.config(text="⏹ 停止服务器")
        self.lbl_status.config(text="运行中", fg="green")
        
        threading.Thread(target=self.run_process, args=(cmd,), daemon=True).start()

    def run_process(self, cmd):
        try:
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
            
            self.root.after(0, self.update_process_info, True, self.process.pid)

            for line in self.process.stdout:
                self.root.after(0, self.append_log, line)

            self.process.wait()
            self.root.after(0, self.server_stopped)

        except FileNotFoundError:
            self.root.after(0, self.append_log, "\n[错误] 在指定的目录下找不到执行程序 (llama.exe 或 llama-server.exe)！\n请确保 llama.cpp 目录选择正确。\n")
            self.root.after(0, self.server_stopped)
        except Exception as e:
            self.root.after(0, self.append_log, f"\n[错误] 发生异常: {str(e)}\n")
            self.root.after(0, self.server_stopped)

    def server_stopped(self):
        self.start_btn.config(text="▶ 启动服务器")
        self.lbl_status.config(text="未运行", fg="red")
        self.update_process_info(False)
        self.append_log("\n[系统] 服务器进程已结束。\n")

    def append_log(self, text):
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = LlamaLauncherApp(root)
    root.mainloop()