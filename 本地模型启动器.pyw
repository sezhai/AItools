import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import os
import json
import webbrowser
import socket
import ctypes

# Windows Ctypes 结构体定义 (用于高性能系统监控)
class _FILETIME(ctypes.Structure):
    _fields_ = [('dwLowDateTime', ctypes.c_ulong), ('dwHighDateTime', ctypes.c_ulong)]

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ('dwLength', ctypes.c_ulong),
        ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong),
        ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong),
        ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong),
        ('ullAvailVirtual', ctypes.c_ulonglong),
        ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
    ]

class _NVMLMemory(ctypes.Structure):
    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]

class _NVMLUtilization(ctypes.Structure):
    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]

class LlamaLauncherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("llama.cpp 启动器")
        
        # 窗口自适应与居中逻辑 (最大 1180x880，小屏幕/高缩放下自适应屏幕高度)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = min(1180, max(960, screen_width - 80))
        window_height = min(880, max(680, screen_height - 100))
        x = max(0, int((screen_width - window_width) / 2))
        y = max(0, int((screen_height - window_height) / 2))
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        
        self._running = False
        self._current_proc = None
        self._external_running = False
        self._is_destroyed = False
        self.vars = {} # 统一管理所有输入变量
        
        # 默认配置文件名
        self.current_config_file = "llama_config.json"
        
        # 初始化系统监控探针 (CPU / 内存 / GPU)
        self._init_sys_monitor()

        self.setup_ui()
        # 窗口关闭协议：防止孤儿进程
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        # 启动时仅尝试加载默认的 llama_config.json (如果存在的话)
        self.load_settings()
        # 异步探测端口上是否已有服务器在运行（避免阻塞窗口显示）
        self.root.after(300, self.check_existing_server)
        # 启动系统资源循环刷新
        self.root.after(200, self._update_sys_stats)

    def setup_ui(self):
        # ====== 核心修复：禁用 Combobox 的默认滚轮事件，防止误触 ======
        self.root.unbind_class("TCombobox", "<MouseWheel>")
        self.root.unbind_class("TCombobox", "<Button-4>")
        self.root.unbind_class("TCombobox", "<Button-5>")

        # ====== 布局搭建：Frame + grid 布局 ======
        self.main_container = ttk.Frame(self.root)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.main_container.columnconfigure(0, weight=1, uniform="ratio_lock") 
        self.main_container.columnconfigure(1, weight=1, uniform="ratio_lock") 
        self.main_container.rowconfigure(0, weight=1)

        # ====== 左侧：参数设置区 ======
        self.left_frame_container = ttk.Frame(self.main_container)
        self.left_frame_container.grid(row=0, column=0, sticky="nsew", padx=(0, 2))

        self.canvas = tk.Canvas(self.left_frame_container, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self.left_frame_container, orient="vertical", command=self.canvas.yview)
        
        # 🟢 修复滚轮穿透：鼠标进入左侧容器时绑定全局滚轮，离开时解绑，解决悬停在输入框/标签时无法滚动的问题
        self.left_frame_container.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.left_frame_container.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))
        self.left_frame_container.bind("<Button-4>", self._on_mousewheel)
        self.left_frame_container.bind("<Button-5>", self._on_mousewheel)

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
        if event.num == 4 or (hasattr(event, 'delta') and event.delta > 0):
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5 or (hasattr(event, 'delta') and event.delta < 0):
            self.canvas.yview_scroll(1, "units")

    # ---- 统一控件生成，自动注册到 self.vars 字典 ----
    def create_input_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=32, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        entry = ttk.Entry(frame, textvariable=var, width=20)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return entry

    def create_combo_row(self, parent, label_text, values, default_val, var_key, readonly=False):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=32, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        cb = ttk.Combobox(frame, textvariable=var, values=values, width=20, state="readonly" if readonly else "normal")
        cb.pack(side=tk.LEFT, fill=tk.X, expand=True)
        return cb
        
    def create_check_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        var = tk.BooleanVar(value=default_val)
        self.vars[var_key] = var
        ttk.Checkbutton(frame, text=label_text, variable=var).pack(anchor=tk.W)

    def create_file_row(self, parent, label_text, default_val, var_key, filetypes=(("All files", "*.*"),), initial_var_key=None):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=32, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        
        entry = ttk.Entry(frame, textvariable=var, width=15)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_file():
            current_path = var.get().strip()
            kwargs = {"filetypes": filetypes}
            
            # 优先使用关联变量（如模型路径）的路径作为初始目录
            if initial_var_key and initial_var_key in self.vars:
                ref_path = self.vars[initial_var_key].get().strip()
                if ref_path:
                    if os.path.exists(ref_path):
                        dir_path = os.path.dirname(ref_path) if os.path.isfile(ref_path) else ref_path
                        if os.path.exists(dir_path):
                            kwargs["initialdir"] = dir_path
            
            # 如果当前字段已有路径，也作为备选
            if not kwargs.get("initialdir") and current_path:
                if os.path.exists(current_path):
                    dir_path = os.path.dirname(current_path) if os.path.isfile(current_path) else current_path
                    if os.path.exists(dir_path):
                        kwargs["initialdir"] = dir_path
                else:
                    parent_dir = os.path.dirname(current_path)
                    if os.path.exists(parent_dir):
                        kwargs["initialdir"] = parent_dir
                        
            filepath = filedialog.askopenfilename(**kwargs)
            if filepath:
                var.set(filepath)
                
        ttk.Button(frame, text="浏览...", command=browse_file, width=8).pack(side=tk.LEFT)
        return entry

    def create_dir_row(self, parent, label_text, default_val, var_key):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(frame, text=label_text, width=32, anchor=tk.W).pack(side=tk.LEFT, padx=(0, 5))
        var = tk.StringVar(value=default_val)
        self.vars[var_key] = var
        
        entry = ttk.Entry(frame, textvariable=var, width=15)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        def browse_dir():
            current_path = var.get().strip()
            kwargs = {}
            
            if current_path:
                if os.path.isdir(current_path):
                    kwargs["initialdir"] = current_path
                else:
                    parent_dir = os.path.dirname(current_path)
                    if os.path.exists(parent_dir):
                        kwargs["initialdir"] = parent_dir
                        
            dirpath = filedialog.askdirectory(**kwargs)
            if dirpath:
                var.set(dirpath)
                
        ttk.Button(frame, text="选择目录...", command=browse_dir, width=8).pack(side=tk.LEFT)

    def build_left_panel(self):
        # --- 1. 基础设置 ---
        g_basic = ttk.LabelFrame(self.left_frame, text="基础设置 (必填)")
        g_basic.pack(fill=tk.X, padx=5, pady=5)
        
        self.create_dir_row(g_basic, "llama.cpp 所在目录:", "", "llama_dir")
        self.create_file_row(g_basic, "模型路径 (-m):", "", "model", 
                             filetypes=[("GGUF Model", "*.gguf"), ("All files", "*.*")])
        self.create_file_row(g_basic, "多模态投影文件 (--mmproj):", "", "mmproj",
                             filetypes=[("GGUF Projector", "*.gguf"), ("All files", "*.*")],
                             initial_var_key="model")
        # 🟢 新增：视觉多模态模型交由 CPU 处理，节省 ~1GB 显存
        self.create_check_row(g_basic, "视觉模型交由CPU处理 (--no-mmproj-offload)", False, "no_mmproj_offload")
        # 🟢 新增：模型别名与 API Key（适配各大客户端/OpenAI API）
        self.create_input_row(g_basic, "模型别名 (-a, --alias):", "", "alias")
        self.create_input_row(g_basic, "API 密钥 (--api-key):", "", "api_key")
        self.create_input_row(g_basic, "监听地址 (--host):", "127.0.0.1", "host")
        self.create_input_row(g_basic, "监听端口 (--port):", "8080", "port")

        # --- 2. 模型参数 ---
        g_model = ttk.LabelFrame(self.left_frame, text="模型参数")
        g_model.pack(fill=tk.X, padx=5, pady=5)
        self.create_combo_row(g_model, "上下文长度 (-c, --ctx-size):", ["16384", "24576", "32768", "65536", "81920", "98304", "131072", "262144"], "16384", "ctx")
        self.create_input_row(g_model, "图像最小Tokens (--image-min-tokens):", "", "image_min_tokens")
        # 🟢 新增：图像最大Tokens限制
        self.create_input_row(g_model, "图像最大Tokens (--image-max-tokens):", "", "image_max_tokens")
        self.create_input_row(g_model, "GPU加速层数 (-ngl):", "", "ngl")
        # 🟢 MoE 专家分流 (MoE模型如 35B / DeepSeek 显存吃紧时分流部分专家到 CPU)
        self.create_input_row(g_model, "CPU MoE专家层数 (-ncmoe):", "", "ncmoe")
        self.create_input_row(g_model, "批处理大小 (-b):", "2048", "b")
        self.create_input_row(g_model, "物理批处理大小 (-ub):", "512", "ub")

        # --- 3. 推理/思考模式 ---
        g_reason = ttk.LabelFrame(self.left_frame, text="推理/思考模式")
        g_reason.pack(fill=tk.X, padx=5, pady=5)
        self.create_combo_row(g_reason, "推理模式 (--reasoning):", ["auto", "on", "off"], "auto", "reasoning", readonly=True)
        self.create_combo_row(g_reason, "思考力度 (--reasoning-effort):", ["default", "minimal", "low", "medium", "high", "xhigh", "max"], "default", "reasoning_effort", readonly=True)
        self.create_input_row(g_reason, "思考预算 (--reasoning-budget):", "", "reasoning_budget")
        self.create_combo_row(g_reason, "思考格式 (--reasoning-format):", ["auto", "none", "deepseek", "deepseek-legacy"], "auto", "reasoning_format", readonly=True)
        self.create_check_row(g_reason, "保留思考内容 (--reasoning-preserve)", False, "reasoning_preserve")

        # --- 4. 性能与内存 ---
        g_perf = ttk.LabelFrame(self.left_frame, text="性能与内存")
        g_perf.pack(fill=tk.X, padx=5, pady=5)
        # 🟢 新增：计算设备与多卡参数
        self.create_input_row(g_perf, "计算设备 (-dev, --device):", "", "device")
        self.create_combo_row(g_perf, "多卡切分模式 (-sm, --split-mode):", ["", "layer", "row", "none"], "", "split_mode", readonly=True)
        self.create_input_row(g_perf, "多卡显存比例 (-ts, --tensor-split):", "", "tensor_split")
        self.create_input_row(g_perf, "主GPU索引 (-mg, --main-gpu):", "", "main_gpu")
        self.create_input_row(g_perf, "CPU线程数 (-t):", "", "threads")
        self.create_input_row(g_perf, "批处理线程数 (-tb):", "", "threads_batch")
        self.create_combo_row(g_perf, "Flash Attention (-fa):", ["auto", "on", "off"], "auto", "fa", readonly=True)
        self.create_combo_row(g_perf, "KV Cache 类型 K (-ctk):", ["f16", "q8_0", "bf16", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl", "turbo4", "turbo3", "turbo2", "turbo8"], "f16", "ctk", readonly=False)
        self.create_combo_row(g_perf, "KV Cache 类型 V (-ctv):", ["f16", "q8_0", "bf16", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl", "turbo4", "turbo3", "turbo2", "turbo8"], "f16", "ctv", readonly=False)
        # 🟢 KV 缓存优化开关 (默认开启；取消勾选将传 --no-kv-offload)
        self.create_check_row(g_perf, "优化/卸载KV缓存 (-kvo)", True, "kvo")
        # 🟢 新增：统一 KV 缓存池
        self.create_check_row(g_perf, "统一KV缓存池 (--kv-unified)", False, "kv_unified")
        # 🟢 新增：缓存块重用 (多轮长对话/RAG首字加速，建议 256 或 512)
        self.create_input_row(g_perf, "缓存块重用 (--cache-reuse):", "", "cache_reuse")
        # 🟢 新版 llama.cpp：统一为 --load-mode
        self.create_combo_row(g_perf, "加载模式 (-lm, --load-mode):", ["", "auto", "none", "mmap", "mlock", "mmap+mlock", "dio"], "", "load_mode", readonly=True)
        # 🟢 新增：大张量按需读取 (节省大模型物理 RAM)
        self.create_combo_row(g_perf, "大张量按需读取 (--tensor-read-lazy):", ["", "auto", "on", "off"], "", "tensor_read_lazy", readonly=True)
        self.create_input_row(g_perf, "缓存 RAM 限制 (--cache-ram):", "", "cache_ram")
        # 🟢 新增：不保留主机 RAM 模型副本
        self.create_check_row(g_perf, "不保留主机RAM副本 (--no-host)", False, "no_host")
        self.create_input_row(g_perf, "上下文检查点 (--ctx-checkpoints):", "", "ctx_checkpoints")

        # --- 5. 请求控制与模板 ---
        g_req = ttk.LabelFrame(self.left_frame, text="请求控制与模板")
        g_req.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_req, "并发槽位数 (-np, --parallel):", "1", "np")
        self.create_check_row(g_req, "启用向量嵌入 (--embedding)", False, "embedding")
        self.create_check_row(g_req, "启用重排序 (--reranking)", False, "reranking")
        self.create_check_row(g_req, "使用 Jinja 模板 (--jinja)", True, "jinja")
        # 🟢 新增：外部 Jinja 模板文件路径
        self.create_file_row(g_req, "外部模板文件 (--chat-template-file):", "", "chat_template_file",
                             filetypes=[("Jinja Template", "*.jinja;*.jinja2;*.j2"), ("All files", "*.*")])
        self.create_input_row(g_req, "指定模板名称 (--chat-template):", "", "chat_template")
        self.create_input_row(g_req, "模板附加参数 (--chat-template-kwargs):", "", "kwargs")

        # --- 5b. 投机解码 ---
        g_spec = ttk.LabelFrame(self.left_frame, text="投机解码")
        g_spec.pack(fill=tk.X, padx=5, pady=5)
        self.create_combo_row(g_spec, "投机解码类型 (--spec-type):", ["", "draft-simple", "draft-mtp", "draft-eagle3", "draft-dflash", "draft-dspark", "ngram-simple", "ngram-mod", "ngram-cache", "ngram-map-k", "ngram-map-k4v"], "", "spec_type")
        
        entry_draft_model = self.create_file_row(g_spec, "草稿模型路径 (--model-draft):", "", "draft_model",
                             filetypes=[("GGUF Model", "*.gguf"), ("All files", "*.*")])
        entry_draft_max = self.create_input_row(g_spec, "草稿最大Tokens (--spec-draft-n-max):", "", "draft_max")
        entry_draft_min = self.create_input_row(g_spec, "草稿最小Tokens (--spec-draft-n-min):", "", "draft_min")
        # 🟢 新增：极关键的投机解码置信度门限（防止吞吐雪崩）及草稿KV缓存类型
        entry_draft_p_min = self.create_input_row(g_spec, "草稿最小概率 (--spec-draft-p-min):", "", "draft_p_min")
        combo_draft_ctk = self.create_combo_row(g_spec, "草稿K缓存类型 (-ctkd):", ["", "f16", "q8_0", "bf16", "q4_0", "q4_1", "iq4_nl", "turbo4", "turbo3", "turbo2", "turbo8"], "", "draft_ctk", readonly=False)
        combo_draft_ctv = self.create_combo_row(g_spec, "草稿V缓存类型 (-ctvd):", ["", "f16", "q8_0", "bf16", "q4_0", "q4_1", "iq4_nl", "turbo4", "turbo3", "turbo2", "turbo8"], "", "draft_ctv", readonly=False)

        # 智能控件联动：区分外挂草稿模型类 vs 内置MTP vs N-gram
        self._ext_draft_entries = [entry_draft_model, combo_draft_ctk, combo_draft_ctv]
        self._ext_draft_frames = [entry_draft_model.master, combo_draft_ctk.master, combo_draft_ctv.master]
        self._general_spec_entries = [entry_draft_max, entry_draft_min, entry_draft_p_min]

        def _update_draft_state(*_):
            spec = self.vars["spec_type"].get().strip()
            is_active = bool(spec)
            # 只有需要外挂草稿模型时才启用模型路径及草稿KV量化（draft-mtp 与 ngram 不需要独立模型文件）
            is_ext_draft = is_active and ("draft" in spec) and (spec != "draft-mtp")
            
            # 通用投机参数（步长、门限）：只要开启投机解码即启用
            for ent in self._general_spec_entries:
                try:
                    ent.configure(state="normal" if is_active else "disabled")
                except tk.TclError:
                    pass
            
            # 外部独立草稿模型参数
            ext_state = "normal" if is_ext_draft else "disabled"
            for ent in self._ext_draft_entries:
                try:
                    ent.configure(state=ext_state)
                except tk.TclError:
                    pass
            for frm in self._ext_draft_frames:
                for child in frm.winfo_children():
                    if isinstance(child, ttk.Button):
                        try:
                            child.configure(state=ext_state)
                        except tk.TclError:
                            pass

        self.vars["spec_type"].trace_add("write", _update_draft_state)
        self.root.after(100, _update_draft_state)

        # --- 6. 采样设置 ---
        g_sample = ttk.LabelFrame(self.left_frame, text="采样设置")
        g_sample.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_sample, "最大生成数 (-n, --n-predict):", "-1", "n_predict")
        self.create_input_row(g_sample, "温度 (--temp):", "0.80", "temp")
        self.create_input_row(g_sample, "Top-P采样 (--top-p):", "0.95", "top_p")
        self.create_input_row(g_sample, "Top-K采样 (--top-k):", "40", "top_k")
        self.create_input_row(g_sample, "最小概率 (--min-p):", "0.05", "min_p")
        self.create_input_row(g_sample, "存在惩罚 (--presence-penalty):", "0.00", "presence_penalty")
        # 🟢 新增：频率惩罚
        self.create_input_row(g_sample, "频率惩罚 (--frequency-penalty):", "0.00", "frequency_penalty")

        # --- 7. 高级采样 ---
        g_adv = ttk.LabelFrame(self.left_frame, text="高级采样")
        g_adv.pack(fill=tk.X, padx=5, pady=5)
        self.create_input_row(g_adv, "重复惩罚 (--repeat-penalty):", "1.00", "repeat_penalty")
        self.create_input_row(g_adv, "重复惩罚范围 (--repeat-last-n):", "64", "repeat_last_n")
        # 🟢 新增：DRY 采样器参数（目前 llama.cpp 效果最佳防复读）
        self.create_input_row(g_adv, "DRY 倍率 (--dry-multiplier):", "", "dry_multiplier")
        self.create_input_row(g_adv, "DRY 基数 (--dry-base):", "", "dry_base")
        self.create_input_row(g_adv, "随机种子 (-s, --seed):", "-1", "seed")

    def build_right_panel(self):
        top_frame = ttk.Frame(self.right_frame)
        top_frame.pack(fill=tk.X, padx=5, pady=(10, 5))
        
        self.start_btn = ttk.Button(top_frame, text="▶ 启动服务器", command=self.toggle_server)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 2))

        ttk.Button(top_frame, text="📂 加载配置", command=self.load_config_dialog).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="💾 保存配置", command=self.save_settings).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="📜 导出批处理脚本", command=self.export_script).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="🌐 打开控制台", command=self.open_webui).pack(side=tk.LEFT, padx=2)
        ttk.Button(top_frame, text="❓ 帮助指南", command=self.open_help_doc).pack(side=tk.LEFT, padx=2)

        status_header_frame = ttk.Frame(self.right_frame)
        status_header_frame.pack(fill=tk.X, padx=5, pady=(8, 0))
        
        ttk.Label(status_header_frame, text="服务器状态").pack(side=tk.LEFT)
        self.lbl_config = ttk.Label(status_header_frame, text=f"当前配置: {os.path.basename(self.current_config_file)}", foreground="blue")
        self.lbl_config.pack(side=tk.RIGHT)

        status_info_frame = ttk.Frame(self.right_frame)
        status_info_frame.pack(fill=tk.X, padx=5, pady=(1, 3))
        self.lbl_status = tk.Label(status_info_frame, text="未运行", fg="red", font=("Microsoft YaHei", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT)
        self.lbl_run_status = ttk.Label(status_info_frame, text="运行状态: 否")
        self.lbl_run_status.pack(side=tk.LEFT, padx=(15, 0))
        self.lbl_pid = ttk.Label(status_info_frame, text="进程号 (PID): -")
        self.lbl_pid.pack(side=tk.LEFT, padx=(15, 0))
        
        ttk.Separator(self.right_frame, orient='horizontal').pack(fill=tk.X, padx=5, pady=2)

        # ====== 系统硬件资源监控区 ======
        sys_frame = ttk.LabelFrame(self.right_frame, text="系统监控")
        sys_frame.pack(fill=tk.X, padx=5, pady=(1, 3))

        sys_frame.columnconfigure(0, weight=0, minsize=235)
        sys_frame.columnconfigure(1, weight=0)
        sys_frame.columnconfigure(2, weight=1)

        # 第0行：CPU 与 内存 (严格分列对齐)
        self.lbl_cpu = ttk.Label(sys_frame, text="CPU: 计算中...", font=("Microsoft YaHei", 9))
        self.lbl_cpu.grid(row=0, column=0, padx=(8, 4), pady=2, sticky="w")

        sep0 = ttk.Label(sys_frame, text="│", foreground="#888888", font=("Microsoft YaHei", 9))
        sep0.grid(row=0, column=1, padx=6, pady=2)

        self.lbl_ram = ttk.Label(sys_frame, text="内存: -- / -- ( -- %)", font=("Microsoft YaHei", 9))
        self.lbl_ram.grid(row=0, column=2, padx=(4, 8), pady=2, sticky="w")

        # 第1行及后续行：显卡核心负载 与 显存 (严格分列对齐)
        self.lbl_gpu_cores = []
        self.lbl_gpu_mems = []
        if self._gpu_names:
            for i, name in enumerate(self._gpu_names):
                row_idx = i + 1
                lbl_core = ttk.Label(sys_frame, text=f"显卡 {i} ({name}): 核心负载 -- %", font=("Microsoft YaHei", 9))
                lbl_core.grid(row=row_idx, column=0, padx=(8, 4), pady=2, sticky="w")

                sep_gpu = ttk.Label(sys_frame, text="│", foreground="#888888", font=("Microsoft YaHei", 9))
                sep_gpu.grid(row=row_idx, column=1, padx=6, pady=2)

                lbl_mem = ttk.Label(sys_frame, text="显存占用 -- / --", font=("Microsoft YaHei", 9))
                lbl_mem.grid(row=row_idx, column=2, padx=(4, 8), pady=2, sticky="w")

                self.lbl_gpu_cores.append(lbl_core)
                self.lbl_gpu_mems.append(lbl_mem)
        else:
            lbl_nogpu = ttk.Label(sys_frame, text="独立显卡: 未检测到 NVIDIA 独立显卡或驱动未就绪", font=("Microsoft YaHei", 9), foreground="gray")
            lbl_nogpu.grid(row=1, column=0, columnspan=3, padx=(8, 4), pady=2, sticky="w")

        ttk.Separator(self.right_frame, orient='horizontal').pack(fill=tk.X, padx=5, pady=2)

        ttk.Label(self.right_frame, text="日志输出").pack(anchor=tk.W, padx=5, pady=(2, 0))
        log_frame = ttk.Frame(self.right_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, bg="black", fg="white", font=("Consolas", 10), width=1)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=log_scrollbar.set)

        bottom_frame = ttk.Frame(self.right_frame)
        bottom_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(bottom_frame, text="清空日志", command=lambda: self.log_text.delete(1.0, tk.END)).pack(side=tk.LEFT)

    def open_help_doc(self):
        """以内部窗口的形式弹出帮助文档"""
        help_win = tk.Toplevel(self.root)
        help_win.title("llama.cpp 启动器参数详解与帮助")
        help_win.geometry("700x750")
        help_win.transient(self.root)
        help_win.grab_set()
        
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 350
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 375
        help_win.geometry(f"+{x}+{y}")

        txt = tk.Text(help_win, font=("Microsoft YaHei", 10), padx=15, pady=15, wrap=tk.WORD, bg="#f9f9f9")
        scrollbar = ttk.Scrollbar(help_win, command=txt.yview)
        txt.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        help_content = """=== llama.cpp 启动器 使用指南 (最新版规范) ===

1. 基础设置 (必填)
llama.cpp 所在目录： 存放 llama.exe、llama-server.exe 或 llama 核心程序文件夹。
模型路径 (-m)： 大语言模型文件绝对路径（.gguf 格式）。
多模态投影文件 (--mmproj)： 视觉模型（LLaVA、Qwen-VL）的投射权重；纯文本模型保持为空。
视觉模型交CPU处理 (--no-mmproj-offload)： 勾选后将视觉投影模型交由 CPU 运算，节省 ~1.0-1.5GB 显存。
模型别名 (-a, --alias)： 映射模型对外名称（如 gpt-4o / default），方便各类 OpenAI API 客户端调用。
API 密钥 (--api-key)： 设置服务鉴权 Token，防误调或满足客户端鉴权必填项。
监听地址 (--host) 与 端口 (--port)： 默认 127.0.0.1 : 8080。

2. 模型参数
上下文长度 (-c, --ctx-size)： 模型最大上下文 Token 数（默认 16384）。
图像 Token 限制 (--image-min-tokens / --image-max-tokens)： 动态分辨率视觉模型单图 Token 上下限。
GPU 加速层数 (-ngl)： 卸载到 GPU 的层数，显存充裕填 99/999。
CPU MoE 专家层数 (-ncmoe)： MoE 模型（如 Qwen-35B-A3B）前 N 层专家留由 CPU 运算。
批处理大小 (-b / -ub)： -b 为逻辑 Batch，-ub 为物理硬件计算 Batch。

3. 推理/思考模式
推理模式 (--reasoning)： auto / on / off。
思考力度 (--reasoning-effort)： default / minimal / low / medium / high / xhigh / max。
思考格式 (--reasoning-format)： auto / none / deepseek / deepseek-legacy。
思考预算 (--reasoning-budget)： 最大思考 Token 数，-1 为不限制。
保留思考内容 (--reasoning-preserve)： 勾选后在上下文历史中保留历史轮次的思考痕迹。

4. 性能与内存
计算设备 (-dev, --device)： 显式指定计算后端或显卡（如 CUDA0 / Vulkan0 / 0），防止双显卡跑错至核显。
多卡切分模式 (-sm, --split-mode)： 多卡切分机制。layer（流水线按层切分，默认且最兼容，适合普通PCIe通道）；row（张量切分，多卡并行算力叠加，适合NVLink/高速双卡）；none（单卡运行）。
多卡显存比例 (-ts, --tensor-split)： 逗号分隔的多卡显存分配权重（如 3,1 或 16,8）。留空则由 llama.cpp 自动按各卡空闲显存比例分配。可用于异构显卡或为主卡预留显存防 OOM。
主 GPU 索引 (-mg, --main-gpu)： 指定主控 GPU 编号（默认为 0）。若 GPU 0 为桌面亮机卡，可填 1 将主任务移至第二张卡。
CPU 线程数 (-t / -tb)： 生成线程与 Batch 提示词处理线程数。
Flash Attention (-fa)： 闪烁注意力（推荐 auto / on），大幅降低显存并提速。
KV Cache 类型 (-ctk / -ctv)： 上下文量化（默认 f16；支持 q8_0/q4_0 及 turbo4/turbo3/turbo2 极致压缩）。
优化/卸载 KV 缓存 (-kvo)： 默认开启；取消勾选将显式传 --no-kv-offload 禁用卸载。
统一 KV 缓存池 (--kv-unified)： 勾选后统筹管理 K/V 缓存池，提升长上下文利用率。
缓存块重用 (--cache-reuse)： 设置 KV 缓存块重用阈值（建议 256 或 512），大幅降低多轮长对话与 RAG 的首字延迟。
加载模式 (-lm, --load-mode)： auto / none / mmap / mlock / mmap+mlock / dio。
大张量按需读取 (--tensor-read-lazy)： on / auto / off，超大嵌入模型在 mmap 下大幅降低 RAM 占用。
缓存 RAM 限制 (--cache-ram)： 限制主机缓存 RAM（设为 0 可关闭内存缓存）。
不保留主机 RAM 副本 (--no-host)： 配合 --cache-ram 0 彻底杜绝主机内存冗余副本。
上下文检查点 (--ctx-checkpoints)： 长上下文回退与分支检查点数（默认 32）。

5. 请求控制与模板
并发槽位数 (-np)： 并发处理槽位数（单用户推荐 1）。
使用 Jinja 模板 (--jinja)： 默认开启；取消勾选将传 --no-jinja。
外部模板文件 (--chat-template-file)： 指定自定义外部 Jinja 模板文件（如 deepseek 格式模板）。
指定模板名称 (--chat-template)： 强制指定内置模板（如 qwen2, deepseek3, chatml 等）。

5b. 投机解码 (Speculative Decoding)
投机解码类型 (--spec-type)：
  - draft-mtp: 多 Token 预测（如 Ornith/DeepSeek），使用模型内置头，无需外挂草稿文件。
  - draft-simple / draft-eagle3 / draft-dflash: 外挂轻量小草稿模型 (--model-draft)。
  - ngram-mod / ngram-simple: 纯 CPU 零显存开销的 N-gram 自推测加速。
草稿最小概率 (--spec-draft-p-min)： 【极关键】投机置信度门限（建议 0.75~0.80），低于此概率提前退出，避免无效草稿拖慢速度。
草稿 Tokens 范围 (--spec-draft-n-max / --spec-draft-n-min)： 单步投机最大/最小生成数量。

6. 采样与高级采样
温度 (--temp) / Top-P / Top-K / Min-P： 标准核采样与最小概率门限。
存在惩罚 (--presence-penalty) / 频率惩罚 (--frequency-penalty)： 重复抑制。
DRY 采样器 (--dry-multiplier / --dry-base)： 当前效果最佳的防复读算法（优于传统 repeat-penalty）。
"""
        txt.insert(tk.END, help_content)
        txt.config(state=tk.DISABLED)

    def open_webui(self):
        host, port = self._current_host_port()
        url = f"http://{host}:{port}"
        try:
            webbrowser.open(url)
            self.append_log(f"\n[系统] 正在浏览器中尝试打开 WebUI: {url}\n")
        except Exception as e:
            self.append_log(f"\n[错误] 无法打开浏览器: {str(e)}\n")

    def update_process_info(self, is_running, pid="-"):
        try:
            if is_running:
                self.lbl_run_status.config(text="运行状态: 是")
                self.lbl_pid.config(text=f"进程号 (PID): {pid}")
            else:
                self.lbl_run_status.config(text="运行状态: 否")
                self.lbl_pid.config(text="进程号 (PID): -")
        except tk.TclError:
            pass

    def load_config_dialog(self):
        initial_dir = os.path.dirname(os.path.abspath(self.current_config_file)) if self.current_config_file else "."
        filepath = filedialog.askopenfilename(
            title="加载配置文件",
            initialdir=initial_dir,
            filetypes=[("JSON 配置文件", "*.json"), ("所有文件", "*.*")]
        )
        if filepath:
            self.load_settings(filepath)

    def save_settings(self):
        initial_dir = os.path.dirname(os.path.abspath(self.current_config_file)) if self.current_config_file else "."
        filepath = filedialog.asksaveasfilename(
            title="保存配置文件",
            initialdir=initial_dir,
            defaultextension=".json",
            initialfile=os.path.basename(self.current_config_file) if self.current_config_file else "llama_config.json",
            filetypes=[("JSON 配置文件", "*.json"), ("所有文件", "*.*")]
        )
        
        if filepath:
            config_data = {k: v.get() for k, v in self.vars.items()}
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=4)
                
                self.current_config_file = filepath
                self.lbl_config.config(text=f"当前配置: {os.path.basename(filepath)}")
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
                
                # 兼容旧版配置迁移：no_mmap/mlock 布尔开关 -> load_mode
                if "load_mode" in self.vars:
                    _valid_lm = ("auto", "none", "mmap", "mlock", "mmap+mlock", "dio")
                    _lm = str(config_data.get("load_mode", "")).strip()
                    if _lm in _valid_lm:
                        self.vars["load_mode"].set(_lm)
                    else:
                        def _as_bool(x):
                            return str(x).strip().lower() in ("1", "true", "yes", "on")
                        _had_old = ("no_mmap" in config_data) or ("mlock" in config_data)
                        if _had_old:
                            _mlock = _as_bool(config_data.get("mlock", False))
                            _no_mmap = _as_bool(config_data.get("no_mmap", False))
                            if _mlock:
                                self.vars["load_mode"].set("mlock")
                            elif _no_mmap:
                                self.vars["load_mode"].set("none")

                for k, v in config_data.items():
                    if k == "load_mode":
                        continue
                    if k in self.vars:
                        var = self.vars[k]
                        if isinstance(var, tk.BooleanVar):
                            if isinstance(v, bool):
                                var.set(v)
                            else:
                                var.set(str(v).strip().lower() in ("1", "true", "yes", "on"))
                        else:
                            if k == "reasoning" and v not in ["auto", "on", "off"]:
                                v = "auto"
                            if k == "reasoning_format" and v not in ["auto", "none", "deepseek", "deepseek-legacy"]:
                                v = "auto"
                            if k in ("ctk", "ctv") and v == "":
                                v = "f16"
                            if k == "reasoning_effort" and v not in ["default", "minimal", "low", "medium", "high", "xhigh", "max"]:
                                v = "default"
                            if k == "spec_type" and v == "none":
                                v = ""
                            var.set(v)
                
                self.current_config_file = filepath
                if hasattr(self, 'lbl_config'):
                    self.lbl_config.config(text=f"当前配置: {os.path.basename(filepath)}")
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
            ("no_mmproj_offload", "--no-mmproj-offload", True),
            ("alias", "--alias", False),
            ("api_key", "--api-key", False),
            ("image_min_tokens", "--image-min-tokens", False),
            ("image_max_tokens", "--image-max-tokens", False),
            ("host", "--host", False),
            ("port", "--port", False),
            ("device", "-dev", False),
            ("split_mode", "-sm", False),
            ("tensor_split", "-ts", False),
            ("main_gpu", "-mg", False),
            ("ctx", "-c", False),
            ("threads", "-t", False), 
            ("threads_batch", "-tb", False), 
            ("fa", "-fa", False),
            ("ctk", "-ctk", False),
            ("ctv", "-ctv", False),
            ("ngl", "-ngl", False),
            ("ncmoe", "-ncmoe", False),
            ("b", "-b", False),
            ("ub", "-ub", False),
            ("np", "-np", False),
            ("embedding", "--embedding", True),
            ("reranking", "--reranking", True),
            ("kv_unified", "--kv-unified", True),
            ("cache_reuse", "--cache-reuse", False),
            ("load_mode", "--load-mode", False),
            ("tensor_read_lazy", "--tensor-read-lazy", False),
            ("cache_ram", "--cache-ram", False),
            ("no_host", "--no-host", True),
            ("ctx_checkpoints", "--ctx-checkpoints", False),
            ("reasoning", "--reasoning", False),
            ("reasoning_effort", "--reasoning-effort", False),
            ("reasoning_budget", "--reasoning-budget", False),
            ("reasoning_format", "--reasoning-format", False),
            ("reasoning_preserve", "--reasoning-preserve", True),
            ("n_predict", "-n", False),
            ("temp", "--temp", False),
            ("top_p", "--top-p", False),
            ("top_k", "--top-k", False),
            ("min_p", "--min-p", False),
            ("presence_penalty", "--presence-penalty", False),
            ("frequency_penalty", "--frequency-penalty", False),
            ("repeat_penalty", "--repeat-penalty", False),
            ("repeat_last_n", "--repeat-last-n", False),
            ("dry_multiplier", "--dry-multiplier", False),
            ("dry_base", "--dry-base", False),
            ("seed", "-s", False),
            ("chat_template_file", "--chat-template-file", False),
            ("chat_template", "--chat-template", False),
            ("kwargs", "--chat-template-kwargs", False),
            ("spec_type", "--spec-type", False),
            ("draft_model", "--model-draft", False),
            ("draft_max", "--spec-draft-n-max", False),
            ("draft_min", "--spec-draft-n-min", False),
            ("draft_p_min", "--spec-draft-p-min", False),
            ("draft_ctk", "--spec-draft-type-k", False),
            ("draft_ctv", "--spec-draft-type-v", False),
        ]

        # 投机解码类型判断
        _spec = self.vars.get("spec_type", tk.StringVar()).get().strip()
        _is_ext_draft = bool(_spec) and ("draft" in _spec) and (_spec != "draft-mtp")
        _is_spec = bool(_spec)
        _has_mmproj = bool(self.vars.get("mmproj", tk.StringVar()).get().strip())

        for var_key, flag, is_boolean in mappings:
            if var_key not in self.vars: continue
            
            # 视觉 CPU 卸载过滤：未选择多模态文件时不传
            if var_key == "no_mmproj_offload" and not _has_mmproj:
                continue
            # 模板互斥过滤：指定外部模板文件时，不传内置模板名称 --chat-template
            if var_key == "chat_template" and self.vars.get("chat_template_file", tk.StringVar()).get().strip():
                continue
            # 投机解码参数智能过滤：非外挂草稿模型不传 --model-draft / 草稿KV类型
            if var_key in ("draft_model", "draft_ctk", "draft_ctv") and not _is_ext_draft:
                continue
            if var_key in ("draft_max", "draft_min", "draft_p_min") and not _is_spec:
                continue

            val = self.vars[var_key].get()
            if is_boolean:
                if val:  
                    cmd.append(flag)
            else:
                if not isinstance(val, str): continue
                val = val.strip()
                if not val: continue
                # reasoning_effort 为 default 时不显式传参
                if var_key == "reasoning_effort" and val == "default":
                    continue
                cmd.extend([flag, val])

        # 🟢 KV 缓存优化：默认启用，取消勾选时显式传 --no-kv-offload
        if "kvo" in self.vars and not self.vars["kvo"].get():
            cmd.append("--no-kv-offload")

        # 🟢 Jinja 模板：显式传参以确保跨 llama.cpp 版本兼容
        if "jinja" in self.vars:
            if self.vars["jinja"].get():
                cmd.append("--jinja")
            else:
                cmd.append("--no-jinja")

        return cmd

    def export_script(self):
        cmd_list = self.build_command()
        
        # BAT 特殊字符处理
        _bat_special = set(' &|<>()^!;=,')
        safe_cmd = []
        for item in cmd_list:
            item = item.replace("%", "%%")
            if " " in item or any(c in _bat_special for c in item.replace("%%", "")):
                escaped = item.replace('"', '\\"')
                safe_cmd.append(f'"{escaped}"')
            else:
                safe_cmd.append(item)

        script_content = "@echo off\nchcp 65001 > nul\ntitle Llama Server 独立脚本\n\n"
        script_content += " ".join(safe_cmd) + "\n\npause"
        
        base_name = os.path.splitext(os.path.basename(self.current_config_file))[0] if self.current_config_file else "server"
        default_bat_name = f"start_server_{base_name}.bat"
        initial_dir = os.path.dirname(os.path.abspath(self.current_config_file)) if self.current_config_file else "."

        filepath = filedialog.asksaveasfilename(
            title="导出独立 BAT 脚本",
            initialdir=initial_dir,
            initialfile=default_bat_name,
            defaultextension=".bat",
            filetypes=[("BAT 批处理脚本", "*.bat"), ("所有文件", "*.*")]
        )
        
        if filepath:
            try:
                with open(filepath, "w", encoding="utf-8-sig") as f:
                    f.write(script_content)
                messagebox.showinfo("成功", f"已成功导出启动脚本：\n{os.path.basename(filepath)}")
                self.append_log(f"[系统] 已生成独立启动脚本: {filepath}\n")
            except Exception as e:
                messagebox.showerror("失败", f"生成脚本失败:\n{str(e)}")

    def _current_host_port(self):
        host = self.vars.get("host").get().strip() or "127.0.0.1"
        port = self.vars.get("port").get().strip() or "8080"
        if host == "0.0.0.0":
            host = "127.0.0.1"
        return host, port

    def detect_server(self):
        host, port = self._current_host_port()
        try:
            with socket.create_connection((host, int(port)), timeout=1.0):
                return True
        except (OSError, ValueError):
            return False

    def check_existing_server(self):
        host, port = self._current_host_port()
        if self.detect_server():
            self._external_running = True
            try:
                self.lbl_status.config(text=f"检测到服务器已在运行 ({host}:{port})", fg="orange")
                self.start_btn.config(text="⏹ 停止服务器")
            except tk.TclError:
                pass
            self.append_log(f"[系统] 检测到 {host}:{port} 已有服务器在运行。\n")

    def _find_pid_on_port(self, host, port):
        if os.name != 'nt':
            return None
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "TCP"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
                    local_addr = parts[1]
                    if ":" in local_addr:
                        actual_port = local_addr.rsplit(":", 1)[1]
                        if actual_port == str(port):
                            return int(parts[4])
        except Exception:
            pass
        return None

    def stop_external_server(self):
        host, port = self._current_host_port()
        pid = self._find_pid_on_port(host, port)
        if pid:
            if not messagebox.askyesno("确认", f"检测到端口 {port} 被 PID {pid} 占用。\n确定要终止该进程及子进程吗？"):
                return
            try:
                kill = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                if kill.returncode == 0:
                    self.append_log(f"[系统] 已终止外部服务器进程 (PID {pid}) 及其进程树。\n")
                else:
                    self.append_log(f"[错误] 终止进程 (PID {pid}) 失败: {kill.stderr.strip() or '返回码 ' + str(kill.returncode)}\n")
            except Exception as e:
                self.append_log(f"[错误] 无法终止外部服务器: {str(e)}\n")
        else:
            if not messagebox.askyesno("确认", f"未定位到端口 {port} 的监听进程。\n是否重置界面状态？"):
                return
            self.append_log("[系统] 未能定位到监听该端口的进程，已重置状态。\n")
        self._external_running = False
        try:
            self.lbl_status.config(text="未运行", fg="red")
            self.start_btn.config(text="▶ 启动服务器")
        except tk.TclError:
            pass
        self.update_process_info(False)

    # ====== 系统硬件资源监控 (纯 ctypes 底层直调，0 子进程开销，<1ms 耗时) ======
    def _init_sys_monitor(self):
        self._prev_cpu_times = None
        self._nvml = None
        self._gpu_handles = []
        self._gpu_names = []
        
        if os.name == 'nt':
            try:
                nvml = ctypes.CDLL('nvml.dll')
                nvml.nvmlInit()
                count = ctypes.c_uint()
                nvml.nvmlDeviceGetCount_v2(ctypes.byref(count))
                for i in range(count.value):
                    handle = ctypes.c_void_p()
                    nvml.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(handle))
                    name_buf = ctypes.create_string_buffer(64)
                    nvml.nvmlDeviceGetName(handle, name_buf, 64)
                    raw_name = name_buf.value.decode('utf-8', errors='ignore')
                    short_name = raw_name.replace('NVIDIA GeForce ', '').replace('NVIDIA ', '')
                    self._gpu_handles.append(handle)
                    self._gpu_names.append(short_name)
                self._nvml = nvml
            except Exception:
                self._nvml = None

    def _shutdown_sys_monitor(self):
        if self._nvml:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml = None

    def _get_cpu_pct(self):
        if os.name != 'nt':
            return None
        try:
            idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            i_val = (idle.dwHighDateTime << 32) | idle.dwLowDateTime
            k_val = (kernel.dwHighDateTime << 32) | kernel.dwLowDateTime
            u_val = (user.dwHighDateTime << 32) | user.dwLowDateTime
            
            if self._prev_cpu_times:
                prev_i, prev_k, prev_u = self._prev_cpu_times
                delta_i = i_val - prev_i
                delta_k = k_val - prev_k
                delta_u = u_val - prev_u
                total_sys = delta_k + delta_u
                if total_sys > 0:
                    pct = max(0.0, min(100.0, ((total_sys - delta_i) / total_sys) * 100.0))
                else:
                    pct = 0.0
            else:
                pct = None
            self._prev_cpu_times = (i_val, k_val, u_val)
            return pct
        except Exception:
            return None

    def _get_ram_info(self):
        if os.name != 'nt':
            return None
        try:
            stat = _MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total_gb = stat.ullTotalPhys / (1024 ** 3)
            used_gb = (stat.ullTotalPhys - stat.ullAvailPhys) / (1024 ** 3)
            load_pct = stat.dwMemoryLoad
            return used_gb, total_gb, load_pct
        except Exception:
            return None

    def _update_sys_stats(self):
        if getattr(self, '_is_destroyed', False):
            return
        try:
            # 1. 处理器负载更新
            cpu_pct = self._get_cpu_pct()
            if cpu_pct is not None and hasattr(self, 'lbl_cpu'):
                self.lbl_cpu.config(text=f"CPU: {cpu_pct:>4.1f}%")

            # 2. 系统内存更新
            ram_info = self._get_ram_info()
            if ram_info and hasattr(self, 'lbl_ram'):
                used_gb, total_gb, load_pct = ram_info
                self.lbl_ram.config(text=f"内存: {used_gb:.1f} GB / {total_gb:.1f} GB ({load_pct}%)")

            # 3. 显卡与显存更新 (支持单卡/多卡，分列精准对齐)
            if self._nvml and self._gpu_handles and hasattr(self, 'lbl_gpu_cores') and hasattr(self, 'lbl_gpu_mems'):
                for i, handle in enumerate(self._gpu_handles):
                    if i < len(self.lbl_gpu_cores) and i < len(self.lbl_gpu_mems):
                        try:
                            mem = _NVMLMemory()
                            self._nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(mem))
                            util = _NVMLUtilization()
                            self._nvml.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util))
                            
                            used_gb = mem.used / (1024 ** 3)
                            total_gb = mem.total / (1024 ** 3)
                            vram_pct = (mem.used / mem.total * 100.0) if mem.total > 0 else 0.0
                            name = self._gpu_names[i]
                            
                            self.lbl_gpu_cores[i].config(
                                text=f"显卡 {i} ({name}): 核心负载 {util.gpu:>2}%"
                            )
                            self.lbl_gpu_mems[i].config(
                                text=f"显存占用 {used_gb:.1f} GB / {total_gb:.1f} GB ({vram_pct:.1f}%)"
                            )
                        except Exception:
                            pass
        except Exception:
            pass

        if not getattr(self, '_is_destroyed', False):
            try:
                self.root.after(1000, self._update_sys_stats)
            except tk.TclError:
                pass

    def on_close(self):
        """窗口关闭处理：防止孤儿进程"""
        self._is_destroyed = True
        self._shutdown_sys_monitor()
        if self._running and self._current_proc and self._current_proc.poll() is None:
            if not messagebox.askyesno("确认退出", "服务器仍在运行，关闭窗口将终止服务器。\n确定要退出吗？"):
                self._is_destroyed = False
                return
            try:
                if os.name == 'nt' and self._current_proc.pid:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self._current_proc.pid)],
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    self._current_proc.terminate()
            except Exception:
                pass
        elif self._external_running:
            if not messagebox.askyesno("确认退出", "检测到外部服务器在运行。\n确定要退出启动器吗？"):
                self._is_destroyed = False
                return
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def toggle_server(self):
        if self._external_running:
            self.stop_external_server()
            return
        if self._running:
            if self._current_proc and self._current_proc.poll() is None:
                try:
                    if os.name == 'nt' and self._current_proc.pid:
                        subprocess.run(["taskkill", "/F", "/T", "/PID", str(self._current_proc.pid)],
                                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        self._current_proc.terminate()
                except Exception:
                    pass
            self._running = False
            self.append_log("\n[系统] 正在终止服务器进程...")
            try:
                self.start_btn.config(text="▶ 启动服务器")
                self.lbl_status.config(text="未运行", fg="red")
            except tk.TclError:
                pass
            self.update_process_info(False)
        else:
            try:
                self.log_text.delete(1.0, tk.END)
            except tk.TclError:
                pass
            self.start_server()

    def start_server(self):
        cmd = self.build_command()

        self.append_log(f"[系统] 正在执行后台命令:\n{' '.join(cmd)}\n")
        self.append_log("-" * 60 + "\n")

        try:
            self.start_btn.config(text="⏹ 停止服务器")
            self.lbl_status.config(text="运行中", fg="green")
        except tk.TclError:
            pass
        self._running = True
        
        threading.Thread(target=self.run_process, args=(cmd,), daemon=True).start()

    def _safe_after(self, ms, func, *args):
        try:
            self.root.after(ms, func, *args)
        except tk.TclError:
            pass

    def run_process(self, cmd):
        proc = None
        try:
            proc = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            self._current_proc = proc
            self._safe_after(0, self.update_process_info, True, proc.pid)

            for line in proc.stdout:
                self._safe_after(0, self.append_log, line)

            proc.wait()
            if self._current_proc is proc:
                self._current_proc = None
                self._safe_after(0, self.server_stopped)

        except FileNotFoundError:
            self._safe_after(0, self.append_log, "\n[错误] 在指定的目录下找不到执行程序 (llama.exe 或 llama-server.exe)！\n请确保 llama.cpp 目录选择正确。\n")
            self._safe_after(0, self.server_stopped)
        except Exception as e:
            self._safe_after(0, self.append_log, f"\n[错误] 发生异常: {str(e)}\n")
            self._safe_after(0, self.server_stopped)

    def server_stopped(self):
        self._running = False
        try:
            self.start_btn.config(text="▶ 启动服务器")
            self.lbl_status.config(text="未运行", fg="red")
        except tk.TclError:
            pass
        self.update_process_info(False)
        self.append_log("\n[系统] 服务器进程已结束。\n")

    def append_log(self, text):
        try:
            # 限制最大行数（超过 10000 行自动清理前 2000 行，防止极端长日志导致 UI 卡顿）
            line_count = int(self.log_text.index('end-1c').split('.')[0])
            if line_count > 10000:
                self.log_text.delete("1.0", "2000.0")
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)
        except tk.TclError:
            pass

if __name__ == "__main__":
    root = tk.Tk()
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    app = LlamaLauncherApp(root)
    root.mainloop()
