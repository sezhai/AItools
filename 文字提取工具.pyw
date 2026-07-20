import os
import time
import sys
import base64
import subprocess
import atexit
import shlex
import asyncio
import signal
import platform
from dataclasses import dataclass, field
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

# ==================== 【环境自检】 ====================
try:
    import requests
    import aiohttp
    import fitz          # PyMuPDF
    import pdfplumber
except ImportError as e:
    print("❌ 缺少必要的依赖库！请执行: pip install requests aiohttp PyMuPDF pdfplumber")
    input("\n按回车键退出...")
    sys.exit(1)

# ==================== 【全局配置数据类】 ====================
@dataclass
class AppConfig:
    input_files: list = field(default_factory=list)
    output_dir: str = ""
    remote_url: str = ""
    remote_model: str = ""
    remote_key: str = ""
    local_url: str = ""
    local_model: str = ""
    llama_dir: str = ""
    llama_cmd: list = field(default_factory=list)
    prompt: str = ""
    
    active_url: str = ""
    active_model: str = ""
    active_key: str = ""

server_process = None

DEFAULT_SYSTEM_PROMPT = (
    "你是一个极其死板、无情的 OCR 视觉提取机器。\n"
    "你的唯一任务是【严格且逐字地转录】图片中肉眼可见的文字，并使用 Markdown 还原排版。\n\n"
    "【最高铁律，违背将导致系统崩溃】：\n"
    "1. 绝对禁止“脑补”与“续写”！图片里有什么字就提取什么字。\n"
    "2. 严禁生成任何与图片无关的论文、报告或模板代码。\n"
    "3. 如果图片大面积空白，提取完可见文字后必须立即停止输出。\n"
    "4. 严禁输出“图中文字如下”、“以下是提取内容”等 AI 废话，直接输出纯文本。"
)

# ==================== 【核心算力调度】 ====================
def cleanup(signum=None, frame=None):
    global server_process
    if server_process and server_process.poll() is None:
        print("\n🛑 正在关闭本地大模型服务，释放显存...")
        server_process.terminate()
        server_process.wait()
    if signum is not None:
        sys.exit(1)

atexit.register(cleanup)
signal.signal(signal.SIGINT, cleanup)
# 🟢 解决问题1：修复 Windows 平台不支持 SIGTERM 导致的 OSError
if platform.system() != "Windows":
    signal.signal(signal.SIGTERM, cleanup)

def start_local_model_server(config: AppConfig):
    global server_process
    print("\n=======================================================")
    print("🚀 准备拉起本地大模型服务作为兜底...")
    
    local_proxies = {"http": None, "https": None}
    try:
        res = requests.get("http://127.0.0.1:8080/health", proxies=local_proxies, timeout=2)
        if res.status_code in [200, 404]:
            print("✅ 探测成功：检测到本地 8080 端口已有模型在运行！直接接入。")
            return True
    except: pass
        
    try:
        server_process = subprocess.Popen(
            config.llama_cmd, 
            cwd=config.llama_dir,
            creationflags=subprocess.CREATE_NEW_CONSOLE 
        )
        print("⏳ 等待本地模型完全加载进显卡 (请勿关闭黑框)...")
        for _ in range(300):
            if server_process.poll() is not None:
                print(f"\n❌ 黑框已闪退！(退出码: {server_process.returncode})")
                return False
            try:
                res = requests.get("http://127.0.0.1:8080/health", proxies=local_proxies, timeout=2)
                if res.status_code in [200, 404]:
                    print("\n✅ 本地视觉大脑就绪！\n")
                    return True
            except requests.exceptions.RequestException: pass 
            time.sleep(1)
        return False
    except Exception as e:
        print(f"\n❌ 本地启动服务发生系统异常: {e}")
        return False

def init_ai_backend(config: AppConfig):
    print("=======================================================")
    print("🌍 正在初始化 AI 算力引擎...")
    
    if config.remote_url and config.remote_model:
        try:
            headers = {"Authorization": f"Bearer {config.remote_key}"} if config.remote_key else {}
            payload = {"model": config.remote_model, "messages": [{"role": "user", "content": "hello"}], "max_tokens": 2}
            res = requests.post(config.remote_url, json=payload, headers=headers, timeout=8)
            if res.status_code == 200:
                print(f"✅ 远程引擎连接成功！使用通道: {config.remote_model}\n")
                config.active_url = config.remote_url
                config.active_model = config.remote_model
                config.active_key = config.remote_key
                return True
        except Exception:
            print(f"⚠️ 远程服务连接失败。")
            
    print("🔄 切换至【本地离线大模型】...")
    config.active_url = config.local_url
    config.active_model = config.local_model
    config.active_key = ""
    return start_local_model_server(config)

# ==================== 【业务逻辑：文字提取与OCR】 ====================
def encode_image_to_base64(image_bytes):
    return base64.b64encode(image_bytes).decode('utf-8')

def is_meaningful_text(text, min_chars=50):
    if not text or len(text) < min_chars: 
        return False
    clean_text = text.replace(" ", "").replace("\n", "").replace("\t", "")
    if len(clean_text) < min_chars // 2: 
        return False
    valid_chars = sum(1 for c in clean_text if '\u4e00' <= c <= '\u9fff' or (c.isascii() and c.isprintable()))
    if valid_chars / len(clean_text) < 0.5:
        return False
    return True

async def extract_text_from_image_async(session, base64_image, config: AppConfig, retries=3):
    headers = {"Authorization": f"Bearer {config.active_key}"} if config.active_key else {}
    payload = {
        "model": config.active_model,
        "messages": [
            {"role": "system", "content": config.prompt},
            {"role": "user", "content": [
                {"type": "text", "text": "请严格转录图片中的文字。"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ],
        "temperature": 0.0,
        "top_p": 0.1,
        "max_tokens": 2048,
        
        # 👇 核心改动：强制关闭大模型思考过程的参数 👇
        "reasoning_format": "auto",
        "reasoning_control": True,
        "chat_template_kwargs": {
            "enable_thinking": False
        }
    }
    
    for attempt in range(retries):
        try:
            async with session.post(config.active_url, json=payload, headers=headers, timeout=300) as response:
                if response.status == 200:
                    data = await response.json()
                    result = data["choices"][0]["message"]["content"].strip()
                    if result.startswith("```markdown"): result = result[11:].strip()
                    if result.endswith("```"): result = result[:-3].strip()
                    return result
                elif response.status in [503, 429]:
                    await asyncio.sleep(4)
                else:
                    return ""
        except Exception:
            pass
    return ""

def fast_extract_pdf_sync(pdf_path):
    final_markdown = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text: final_markdown.append(text)
            for table in page.extract_tables():
                if not table or len(table) < 2: continue
                # 🟢 解决问题4：计算表格最大列数，补齐短行空格，防止 Markdown 渲染破损
                max_cols = max(len(row) for row in table)
                final_markdown.append("\n\n### 提取的表格\n")
                rows = []
                for row in table:
                    padded_row = list(row) + [""] * (max_cols - len(row))
                    clean_row = [str(cell).replace('\n', ' ').strip() if cell is not None else "" for cell in padded_row]
                    rows.append("| " + " | ".join(clean_row) + " |")
                separator = "| " + " | ".join(["---"] * max_cols) + " |"
                rows.insert(1, separator)
                final_markdown.append("\n".join(rows) + "\n")
    return "\n".join(final_markdown)

async def ocr_worker(queue: asyncio.Queue, session: aiohttp.ClientSession, results: list, config: AppConfig, total_pages: int):
    while True:
        task = await queue.get()
        if task is None:
            break
        i, img_bytes = task
        base64_img = encode_image_to_base64(img_bytes)
        text = await extract_text_from_image_async(session, base64_img, config)
        
        # 🟢 解决问题3：OCR 失败或内容为空时，不覆盖空字符，而是存入占位警告
        if text:
            results[i] = text
            print(f"    ✅ 第 [{i+1}/{total_pages}] 页 OCR 解析完成！")
        else:
            results[i] = f"<!-- ⚠️ 第 {i+1} 页 OCR 解析失败或返回空白 -->"
            print(f"    ❌ 第 [{i+1}/{total_pages}] 页 OCR 解析失败或为空！")
            
        queue.task_done()

async def ocr_extract_pdf(session: aiohttp.ClientSession, pdf_path, config: AppConfig):
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    results = [None] * total_pages
    queue = asyncio.Queue(maxsize=6)
    
    async def producer():
        for i in range(total_pages):
            page = doc.load_page(i)
            zoom = 200.0 / 72.0
            w = page.rect.width * zoom
            h = page.rect.height * zoom
            max_pixels = 3_500_000 
            if (w * h) > max_pixels:
                zoom = zoom * ((max_pixels / (w * h)) ** 0.5)
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix)
            await queue.put((i, pix.tobytes("jpeg")))
        doc.close()

    print(f"    👁️ 启动流式视觉引擎 ({total_pages} 页, 并发数: 3)...")
    prod_task = asyncio.create_task(producer())
    workers = [asyncio.create_task(ocr_worker(queue, session, results, config, total_pages)) for _ in range(3)]
    
    # 🟢 解决问题2：用 try-finally 避免抛异常时造成 workers 永久死锁
    try:
        await prod_task
        await queue.join()
    except Exception as e:
        print(f"    ❌ PDF读取预处理发生异常: {e}")
    finally:
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
    
    valid_results = [r for r in results if r is not None]
    return "\n\n---\n\n".join(valid_results) if valid_results else ""

async def smart_process_pdf(session: aiohttp.ClientSession, pdf_path, config: AppConfig):
    print(f"\n📄 扫描 PDF: {os.path.basename(pdf_path)}")
    fast_text = await asyncio.to_thread(fast_extract_pdf_sync, pdf_path)
    
    if not is_meaningful_text(fast_text):
        print("    ⚠️ 无底层文本或疑似乱码，切换至视觉提取通道...")
        return await ocr_extract_pdf(session, pdf_path, config)
    else:
        print("    ⚡ 检测到标准文本层，已极速解析。")
        return fast_text

async def process_image(session: aiohttp.ClientSession, img_path, config: AppConfig):
    print(f"\n🖼️ 解析图片: {os.path.basename(img_path)} ...")
    with open(img_path, "rb") as f:
        img_bytes = f.read()
    
    text = await extract_text_from_image_async(session, encode_image_to_base64(img_bytes), config)
    print("    ✅ 解析完成！" if text else "    ❌ 解析失败！")
    return text

# ==================== 【GUI 配置界面】 ====================
class SetupGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("文字智能提取工具 v3.1 (终极完善版)")
        
        # 🟢 解决问题6：恢复屏幕居中防截断，并锁死拖拽缩放
        window_width = 720
        window_height = 860
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        x = int((screen_width - window_width) / 2)
        y = int((screen_height - window_height) / 2)
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.root.resizable(False, False)
        
        self.app_config = AppConfig()
        self.is_ready = False
        
        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.remote_url = tk.StringVar(value="")
        self.remote_model = tk.StringVar(value="")
        self.remote_key = tk.StringVar(value="")
        self.local_url = tk.StringVar(value="http://127.0.0.1:8080/v1/chat/completions")
        self.local_model = tk.StringVar(value="Qwen3.5-4B")
        self.llama_dir = tk.StringVar(value=r"D:\Program files\Llama")
        
        self.create_widgets()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="⚙️ 文字智能提取工具", font=("微软雅黑", 16, "bold")).pack(pady=(0, 5))

        file_frame = ttk.LabelFrame(main_frame, text=" 📂 1. 任务设置 (必填) ", padding="10")
        file_frame.pack(fill=tk.X, pady=5)
        
        f_sub = ttk.Frame(file_frame)
        f_sub.pack(fill=tk.X, pady=8)
        ttk.Entry(f_sub, textvariable=self.input_dir, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,10))
        ttk.Button(f_sub, text="选择源文件夹 (递归扫描)", command=self.select_input_dir, width=22).pack(side=tk.RIGHT)
        
        d_sub = ttk.Frame(file_frame)
        d_sub.pack(fill=tk.X, pady=8)
        ttk.Entry(d_sub, textvariable=self.output_dir, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,10))
        ttk.Button(d_sub, text="选择 Markdown 导出目录", command=self.select_out_dir, width=22).pack(side=tk.RIGHT)

        remote_frame = ttk.LabelFrame(main_frame, text=" ☁️ 2. 远程视觉模型配置 (优选) ", padding="10")
        remote_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(remote_frame, text="API URL:").grid(row=1, column=0, sticky=tk.E, padx=5, pady=2)
        ttk.Entry(remote_frame, textvariable=self.remote_url, width=60).grid(row=1, column=1, sticky=tk.W)
        
        ttk.Label(remote_frame, text="模型名称:").grid(row=2, column=0, sticky=tk.E, padx=5, pady=2)
        ttk.Entry(remote_frame, textvariable=self.remote_model, width=60).grid(row=2, column=1, sticky=tk.W)
        
        ttk.Label(remote_frame, text="API Key:").grid(row=3, column=0, sticky=tk.E, padx=5, pady=2)
        ttk.Entry(remote_frame, textvariable=self.remote_key, width=60, show="*").grid(row=3, column=1, sticky=tk.W)

        local_frame = ttk.LabelFrame(main_frame, text=" 💻 3. 本地兜底模型配置 ", padding="10")
        local_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        ttk.Label(local_frame, text="API URL:").grid(row=0, column=0, sticky=tk.E, padx=5, pady=2)
        ttk.Entry(local_frame, textvariable=self.local_url, width=60).grid(row=0, column=1, sticky=tk.W)
        
        ttk.Label(local_frame, text="模型名称:").grid(row=1, column=0, sticky=tk.E, padx=5, pady=2)
        ttk.Entry(local_frame, textvariable=self.local_model, width=60).grid(row=1, column=1, sticky=tk.W)

        d_llama = ttk.Frame(local_frame)
        d_llama.grid(row=2, column=1, sticky=tk.W + tk.E)
        ttk.Label(local_frame, text="Llama 目录:").grid(row=2, column=0, sticky=tk.E, padx=5, pady=2)
        ttk.Entry(d_llama, textvariable=self.llama_dir, width=48).pack(side=tk.LEFT, padx=(0,5))
        ttk.Button(d_llama, text="浏览并生成命令", command=self.select_llama_dir).pack(side=tk.LEFT)

        ttk.Label(local_frame, text="启动参数:\n(从 -m 开始)").grid(row=3, column=0, sticky=tk.NE, padx=5, pady=5)
        self.cmd_text = tk.Text(local_frame, height=4, width=60, wrap=tk.WORD, font=("Consolas", 9))
        self.cmd_text.grid(row=3, column=1, sticky=tk.W + tk.E, pady=5)
        self.cmd_text.insert(tk.END, self.get_dynamic_cmd_string(self.llama_dir.get()))

        prompt_frame = ttk.LabelFrame(main_frame, text=" 📝 4. 系统提示词 (System Prompt) ", padding="10")
        prompt_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.prompt_text = tk.Text(prompt_frame, height=7, wrap=tk.WORD, font=("微软雅黑", 9))
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        self.prompt_text.insert(tk.END, DEFAULT_SYSTEM_PROMPT)

        ttk.Button(main_frame, text="🚀 应用配置并开始处理", command=self.start_processing).pack(fill=tk.X, pady=(10, 0))

    def get_dynamic_cmd_string(self, base_dir):
        return f'-m "{os.path.join(base_dir, "Models", "Qwen3.5-4B", "Qwen3.5-4B-Q4_K_M.gguf")}" --mmproj "{os.path.join(base_dir, "Models", "Qwen3.5-4B", "mmproj-BF16.gguf")}" --image-min-tokens 1024 --host 127.0.0.1 --port 8080 -ngl 99 -c 16384 -b 2048 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --ctx-checkpoints 16 --jinja -n 2048'

    def select_input_dir(self):
        folder = filedialog.askdirectory(title="选择包含待处理文件的目录 (自动扫描子目录)")
        if folder:
            supported_exts = ('.pdf', '.png', '.jpg', '.jpeg', '.bmp')
            found_files = []
            
            for root_dir, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith(supported_exts):
                        found_files.append(os.path.join(root_dir, f))
            
            self.input_dir.set(folder)
            self.app_config.input_files = found_files
            
            if not found_files:
                messagebox.showwarning("提示", "该目录及子目录下未找到任何支持的 PDF 或图片文件！")

    def select_out_dir(self):
        folder = filedialog.askdirectory(title="选择输出目录")
        if folder: self.output_dir.set(folder)

    def select_llama_dir(self):
        folder = filedialog.askdirectory()
        if folder:
            self.llama_dir.set(folder)
            self.cmd_text.delete("1.0", tk.END)
            self.cmd_text.insert(tk.END, self.get_dynamic_cmd_string(folder))

    def start_processing(self):
        if not self.app_config.input_files:
            return messagebox.showwarning("提示", "请选择有效的源文件夹！")
        if not self.output_dir.get():
            return messagebox.showwarning("提示", "请选择 Markdown 的导出目录！")
            
        raw_cmd = self.cmd_text.get("1.0", tk.END).strip()
        is_remote_ready = bool(self.remote_url.get() and self.remote_model.get())
        
        if not is_remote_ready:
            if not raw_cmd: return messagebox.showerror("错误", "启动参数为空！")
            if not os.path.exists(os.path.join(self.llama_dir.get(), "llama-server.exe")):
                return messagebox.showerror("错误", "找不到 llama-server.exe！")
                
        try:
            parsed = shlex.split(raw_cmd.replace('\\', '/'), posix=True)
            self.app_config.llama_cmd = [os.path.join(self.llama_dir.get(), "llama-server.exe")] + [a.replace('/', '\\') for a in parsed]
        except Exception as e:
            return messagebox.showerror("错误", f"启动参数解析失败：\n{e}")
            
        self.app_config.prompt = self.prompt_text.get("1.0", tk.END).strip()
        self.app_config.output_dir = self.output_dir.get()
        self.app_config.remote_url = self.remote_url.get().strip()
        self.app_config.remote_model = self.remote_model.get().strip()
        self.app_config.remote_key = self.remote_key.get().strip()
        self.app_config.local_url = self.local_url.get().strip()
        self.app_config.local_model = self.local_model.get().strip()
        self.app_config.llama_dir = self.llama_dir.get().strip()

        self.is_ready = True
        self.root.destroy()

# ==================== 【主控程序 (异步入口)】 ====================
async def main_async(config: AppConfig):
    print("=======================================================")
    print("    👁️ 文字智能提取流水线 (高鲁棒批处理版)    ")
    print("=======================================================")
    
    if not init_ai_backend(config): sys.exit(1)

    print(f"\n📂 共扫描到 {len(config.input_files)} 个任务文件，即将开始流水线作业。")
    start_time = time.time()
    
    # 🟢 解决问题5：提取 Session 到最高层进行复用，免去批量图片重复建连开销
    async with aiohttp.ClientSession(trust_env=False) as session:
        for idx, file_path in enumerate(config.input_files, 1):
            filename = os.path.basename(file_path)
            print(f"\n[{idx}/{len(config.input_files)}] 正在处理: {filename} =============================")
            
            output_path = os.path.join(config.output_dir, f"Extracted_{os.path.splitext(filename)[0]}.md")
            
            try:
                ext = os.path.splitext(filename)[1].lower()
                if ext == '.pdf':
                    content = await smart_process_pdf(session, file_path, config)
                else:
                    content = await process_image(session, file_path, config)
                
                with open(output_path, "w", encoding="utf-8") as f:
                    if content:
                        f.write(content)
                        print(f"✅ [{filename}] 归档成功: {output_path}")
                    else:
                        f.write("<!-- ⚠️ 警告：该文件 OCR 提取失败或返回了空结果 -->")
                        print(f"⚠️ [{filename}] 结果为空或失败，已写入占位文件！")
            except Exception as e:
                print(f"❌ [{filename}] 处理异常跳过: {e}")

    print("\n" + "="*55)
    print(f"🎉 全部流转完毕！总耗时: {round(time.time() - start_time, 1)} 秒")
    print("="*55)
    input("\n按回车键退出，系统将自动关闭相关服务...")

def main():
    root = tk.Tk()
    app = SetupGUI(root)
    root.mainloop()
    
    if app.is_ready:
        asyncio.run(main_async(app.app_config))
    else:
        print("🛑 用户取消了操作，程序退出。")

if __name__ == "__main__":
    main()
