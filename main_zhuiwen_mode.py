import tkinter as tk
from tkinter import scrolledtext, messagebox, ttk, filedialog
import threading
import requests
import json
import re
from pathlib import Path
from datetime import datetime


# --- API 调用函数 (新增 system_prompt 参数) ---

def call_api_stream(prompt, api_key, model_name, system_prompt):
    """
    通过 requests 库调用流式 API，并将文本块通过 yield 返回。
    新增 system_prompt 参数用于设置模型的行为。
    """
    url = "https://api.bltcy.cn/v1/chat/completions"

    # 确保 API Key 包含 Bearer 前缀
    auth_header = api_key

    payload = {
        "model": model_name,
        "stream": True,
        "messages": [
            {"role": "system", "content": system_prompt},  # <<< 动态设置 System Prompt
            {"role": "user", "content": prompt}
        ]
    }

    headers = {
        "Accept": "text/event-stream",
        "Authorization": auth_header,
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, stream=True, timeout=60)

        if response.status_code != 200:
            error_details = response.text
            raise Exception(f"API HTTP 错误: {response.status_code}. 详情: {error_details[:200]}...")

        for line in response.iter_lines():
            if line:
                line_str = line.decode('utf-8')
                if line_str.startswith("data:"):
                    data_str = line_str[5:].strip()

                    if data_str == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                        content = data.get("choices", [{}])[0].get("delta", {}).get("content", "")

                        if content:
                            yield content

                    except json.JSONDecodeError:
                        continue

    except requests.exceptions.RequestException as e:
        print(e)
    #     raise Exception(f"网络连接或请求错误: {e}")
    # except Exception as e:
    #     raise e


# ----------------------------------------


class AIChatApp:
    # --- 模型列表 (保持不变) ---
    MODEL_LIST = [
        "gpt-5.1",
        "gpt-5.1-codex",
        "gemini-3-pro-preview",
        "claude-opus-4-5-20251101-thinking",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001"
    ]

    # --- System Prompt 映射表 (保持不变) ---
    SYSTEM_PROMPT_MAP = {
        "程序代码助手": (
            "You are a professional senior programmer."
            "- Only answer programming-related questions"
            "- Code first, explanations concise"
            "- Follow best practices and design patterns"
            "- Consider edge cases and error handling"
        ),
        "通用Ai助手": (
            "You are a helpful assistant."
        ),
        "中文/英文互译专家": (
            "你是一位专业的中文和英文语言专家。"
            "请给出中英文的双译结果，通过分段显示中文翻译和英文翻译结果。"
        )
    }

    def __init__(self, master):
        self.master = master
        master.title("对话式 AI 助手 (Tkinter)")
        master.option_add('*Font', 'Arial 10')

        self.api_key = tk.StringVar(value="Bearer YOUR_API_KEY_HERE")
        self.selected_model = tk.StringVar(value=self.MODEL_LIST[0])
        self.save_directory = None

        # 新增：存储当前选择的 System Prompt 场景名称
        self.system_scenario_name = tk.StringVar(value=list(self.SYSTEM_PROMPT_MAP.keys())[0])

        # <<< 新增：追问模式复选框状态变量
        self.continuous_mode = tk.BooleanVar(value=True)

        self.current_user_prompt = ""
        self.current_ai_response = ""
        self.in_code_block = False

        # --- 1. Key & Model & Scenario & Save Path 输入模块 (头部) ---
        self.config_frame = tk.Frame(master, padx=10, pady=5)
        self.config_frame.pack(fill='x', padx=10, pady=(10, 5))

        # 1.1 Key 输入部分 (保持不变)
        self.key_label = tk.Label(self.config_frame, text="🔑 API Key:")
        self.key_label.pack(side='left', padx=(0, 5))

        self.key_entry = tk.Entry(
            self.config_frame,
            textvariable=self.api_key,
            width=20,
            bd=1,
            relief='groove',
            fg='red'
        )
        self.key_entry.pack(side='left', fill='x', expand=False, padx=(0, 10))

        self.key_entry.bind('<FocusIn>', self.clear_placeholder)
        self.key_entry.bind('<FocusOut>', self.add_placeholder)

        # 1.2 模型选择下拉菜单部分 (保持不变)
        self.model_label = tk.Label(self.config_frame, text="🤖 Model:")
        self.model_label.pack(side='left', padx=(5, 5))

        self.model_combobox = ttk.Combobox(
            self.config_frame,
            textvariable=self.selected_model,
            values=self.MODEL_LIST,
            state="readonly",
            width=12
        )
        self.model_combobox.pack(side='left', fill='x', expand=False)
        self.model_combobox.current(0)

        # --- 1.3 System Prompt 场景选择下拉菜单部分 (保持不变) ---
        self.scenario_label = tk.Label(self.config_frame, text="🎭 场景:")
        self.scenario_label.pack(side='left', padx=(10, 5))  # 增加间距

        self.scenario_combobox = ttk.Combobox(
            self.config_frame,
            textvariable=self.system_scenario_name,
            values=list(self.SYSTEM_PROMPT_MAP.keys()),
            state="readonly",
            width=12
        )
        self.scenario_combobox.pack(side='left', fill='x', expand=False)
        self.scenario_combobox.current(0)
        # --------------------------------------------------

        # 1.4 文件夹选择部分 (保持不变)
        self.folder_label = tk.Label(self.config_frame, text="📁 记录路径:")
        self.folder_label.pack(side='left', padx=(15, 5))  # 增加左侧间距

        self.folder_path_display = tk.StringVar(value="未选择")
        self.folder_display_entry = tk.Entry(
            self.config_frame,
            textvariable=self.folder_path_display,
            width=8,
            state='readonly'
        )
        self.folder_display_entry.pack(side='left', fill='x', expand=False, padx=(0, 5))

        self.select_folder_button = tk.Button(
            self.config_frame,
            text="选择文件夹",
            command=self.select_save_directory
        )
        self.select_folder_button.pack(side='left')
        # ----------------------------

        # --- 2. 返回数据模块 (中间) ---
        self.output_frame = tk.Frame(master)
        self.output_frame.pack(fill='both', expand=True, padx=10, pady=5)

        self.output_text = scrolledtext.ScrolledText(
            self.output_frame,
            wrap=tk.WORD,
            state='disabled',
            font=('Arial', 13),
            bg='#f0f0f0',
            fg='#333333',
            padx=12,
            pady=12
        )
        self.output_text.pack(fill='both', expand=True)

        # 定义 Markdown 标签样式 (保持不变)
        self.output_text.tag_config('user', foreground='#000080', font=('Arial', 10, 'bold'))
        self.output_text.tag_config('ai_response', foreground='#006400')
        self.output_text.tag_config('error', foreground='#FF0000', font=('Arial', 10, 'bold'))
        self.output_text.tag_config('bold', font=('Arial', 10, 'bold'), foreground='#2c3e50')
        self.output_text.tag_config('code_block', background='#2d2d2d', foreground='#cccccc', font=('Courier', 10))

        # --- 3. 输入窗口 (底部) ---
        self.input_frame = tk.Frame(master, pady=10)
        self.input_frame.pack(fill='x', padx=10, pady=(5, 10))

        # 3.1 左侧：输入框
        self.input_entry = tk.Text(
            self.input_frame,
            height=6,
            wrap=tk.WORD,
            font=('Arial', 10),
            bd=1,
            relief='groove'
        )
        self.input_entry.pack(side='left', fill='x', expand=True, padx=(0, 10))

        self.input_entry.bind("<Shift-Return>", self.insert_newline)
        self.input_entry.bind("<Return>", self.send_message_event)

        # 3.2 右侧：控制和按钮 (使用 grid 布局实现垂直对齐)
        self.control_frame = tk.Frame(self.input_frame)
        self.control_frame.pack(side='right', fill='y')  # 使控制框占满父容器的高度

        # 配置 control_frame 的行权重，确保发送按钮占据大部分空间
        self.control_frame.grid_rowconfigure(0, weight=1)  # 第0行 (复选框)
        self.control_frame.grid_rowconfigure(1, weight=10)  # 第1行 (发送按钮)

        # <<< 优化 1：连问模式复选框
        self.continuous_checkbox = tk.Checkbutton(
            self.control_frame,
            text="连问模式",
            variable=self.continuous_mode,
            onvalue=True,
            offvalue=False,
            anchor='w'  # 左对齐复选框文本
        )
        # 使用 grid 布局，将其定位在顶部，并让其文本左对齐 (sticky='w')
        self.continuous_checkbox.grid(row=0, column=0, sticky='w', pady=(5, 2))

        # 3.3 发送按钮
        self.send_button = tk.Button(
            self.control_frame,
            text="发送",
            command=self.send_message,
            # height=5, # 移除固定高度，改为使用 sticky 填充垂直空间
            width=8
        )
        # <<< 优化 2：使用 grid 布局，使其填充水平和垂直空间 (sticky='nsew')
        # pady=(2, 5) 保持与复选框的间距
        self.send_button.grid(row=1, column=0, sticky='nsew', pady=(2, 5))

        master.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_closing(self):
        self.master.destroy()

    # --- 文件夹选择逻辑 (保持不变) ---
    def select_save_directory(self):
        """打开文件夹选择对话框，并更新保存路径"""
        directory = filedialog.askdirectory(
            parent=self.master,
            initialdir=Path.home(),
            title="选择保存聊天记录的文件夹"
        )
        if directory:
            self.save_directory = Path(directory)
            self.folder_path_display.set(self.save_directory.name)
            self._append_simple_text(f"\n[系统消息] 聊天记录保存路径已设置为: {self.save_directory.name}\n",
                                     'ai_response')
        else:
            self.save_directory = None
            self.folder_path_display.set("未选择")

    # --- Key & 输入逻辑 (保持不变) ---
    def clear_placeholder(self, event):
        if self.api_key.get() == "Bearer YOUR_API_KEY_HERE":
            self.api_key.set("")
            self.key_entry.config(fg='orange')

    def add_placeholder(self, event):
        if not self.api_key.get():
            self.api_key.set("Bearer YOUR_API_KEY_HERE")
            self.key_entry.config(fg='gray')

    def insert_newline(self, event):
        """处理 Shift+Enter 快捷键，插入一个换行符"""
        if self.input_entry.cget('state') == 'normal':
            self.input_entry.insert(tk.INSERT, "\n")
            return "break"
        return

    def send_message_event(self, event):
        """处理 Enter 快捷键，发送消息"""
        if self.input_entry.cget('state') == 'normal':
            self.send_message()
        return "break"

    # <<< 新增：获取聊天记录的方法
    def get_conversation_history(self):
        """获取 output_text 中所有的文本内容 (即 '返回数据模块 (中间)' 的本次聊天全部)"""
        # 使用 '1.0' 到 tk.END 获取所有内容
        # 减去最后的换行符，因为 tk.END 会包含一个额外的换行符
        return self.output_text.get("1.0", tk.END).strip()

    def send_message(self):
        # 原始用户输入 (用于保存)
        original_prompt = self.input_entry.get("1.0", tk.END).strip()

        current_key = self.api_key.get().strip()
        selected_model_name = self.selected_model.get()
        selected_scenario_name = self.system_scenario_name.get()  # <<< 获取选择的场景名称

        if not original_prompt: return

        if not current_key or current_key == "Bearer YOUR_API_KEY_HERE":
            messagebox.showerror("错误", "请先在顶部输入您的 API Key。")
            return

        if not selected_model_name:
            messagebox.showerror("错误", "请选择一个大模型。")
            return

        # 1. 获取 System Prompt 内容
        system_prompt_content = self.SYSTEM_PROMPT_MAP.get(selected_scenario_name)

        if not system_prompt_content:
            messagebox.showerror("错误", "选择的场景配置无效。")
            return

        # 检查保存路径
        if not self.save_directory or not self.save_directory.is_dir():
            messagebox.showerror("错误", "请先通过 '选择文件夹' 按钮设置有效的聊天记录保存路径，才能发送对话。")
            return

        # 2. <<< 追问模式逻辑：构造最终发送给 API 的 prompt
        final_prompt = original_prompt
        if self.continuous_mode.get():
            # 获取当前所有聊天记录
            history = self.get_conversation_history()

            # 构造追问模式的前置提示词
            pre_prompt = (
                "接下来的回复请基于之前的聊天记录进行生成，我们之前的聊天记录如下："
                f"\n--- 历史聊天记录 ---\n{history}\n"
                "--- 历史聊天记录结束 ---\n"
            )

            # 将前置提示词和本次用户输入拼接
            final_prompt = pre_prompt + original_prompt

            # 可选：在界面显示一个提示，但不保存到文件
            self._append_simple_text(f"\n[系统消息] 追问模式已启用，拼接了 {len(history)} 个字符的历史记录。",
                                     'ai_response')

        # 3. 初始化并缓存用户输入 (注意：current_user_prompt 缓存的是原始输入，用于保存)
        self.in_code_block = False
        self.current_user_prompt = original_prompt  # 缓存原始用户输入
        self.current_ai_response = ""

        # 4. 更新 GUI 状态并显示用户输入
        self.input_entry.config(state='disabled')
        self.send_button.config(state='disabled')
        self.continuous_checkbox.config(state='disabled')  # 禁用复选框

        self._append_simple_text(
            f"\n--- 用户 (模型: {selected_model_name}, 场景: {selected_scenario_name}): ---\n{original_prompt}\n",
            # 显示原始输入
            'user')
        self._append_simple_text("\n--- AI 助手: ---\n", 'ai_response')

        # 5. 清空输入框
        self.input_entry.delete("1.0", tk.END)

        # 6. 启动新线程处理 API 调用，传入最终构造的 final_prompt
        self.stream_thread = threading.Thread(
            target=self._run_api_stream,
            args=(final_prompt, current_key, selected_model_name, system_prompt_content)
        )
        self.stream_thread.start()

    def _run_api_stream(self, prompt, key, model_name, system_prompt_content):
        """在新线程中执行 API 调用、更新 UI，并在结束时保存历史记录"""
        try:
            generator = call_api_stream(prompt, key, model_name, system_prompt_content)
            for chunk in generator:
                self.master.after(0, self._process_stream_chunk, chunk)

            self.master.after(0, self._append_simple_text, "\n[对话结束]\n", 'ai_response')

            # 成功结束后，保存历史记录 (使用 self.current_user_prompt)
            self.master.after(0, self._save_chat_history, self.current_user_prompt, self.current_ai_response,
                              model_name)

        except Exception as e:
            # 失败结束后，保存历史记录
            self.master.after(0, self._save_chat_history, self.current_user_prompt, self.current_ai_response,
                              model_name)
            self.master.after(0, lambda: self._append_simple_text(
                f"\n[错误信息] API 调用失败或网络错误: {e}\n", 'error')
                              )

        finally:
            self.master.after(0, self._enable_input)

    # --- 文件保存逻辑 (修改：使用 self.current_user_prompt) ---
    def _save_chat_history(self, prompt, response, model_name):
        """将当前对话保存到本地Markdown文件"""
        if not self.save_directory or not self.save_directory.is_dir():
            return

        today_date = datetime.now().strftime("%Y%m%d")
        filename = f"{today_date}-chatbot-data.md"
        save_path = self.save_directory / filename

        current_time = datetime.now().strftime("%H:%M:%S")

        # 注意：此处 prompt 已经是原始的用户输入 (self.current_user_prompt)，满足不保存连问提示词的要求
        content = f"""
## 🤖 对话记录 ({today_date})

### **[{current_time}]** 模型: {model_name}

#### 用户:
{prompt}

#### AI 助手:
{response}

---
"""
        try:
            with save_path.open('a', encoding='utf-8') as f:
                f.write(content)

            self.master.after(0, lambda: self._append_simple_text(
                f"\n[系统消息] 对话已保存至文件: {save_path.name}\n", 'ai_response')
                              )

        except Exception as e:
            self.master.after(0, lambda: messagebox.showerror(
                "保存错误", f"保存聊天记录失败：{e}。请检查文件夹权限。")
                              )

    # --- Markdown 渲染和辅助函数 (保持不变) ---

    def _process_stream_chunk(self, chunk):
        self.output_text.config(state='normal')

        code_block_tag = '```'
        if code_block_tag in chunk:
            parts = chunk.split(code_block_tag)

            for i, part in enumerate(parts):
                if i > 0:
                    self.in_code_block = not self.in_code_block

                    self.current_ai_response += code_block_tag
                    self._insert_and_scroll(code_block_tag, 'code_block' if self.in_code_block else 'ai_response')

                if part:
                    self.current_ai_response += part
                    self._insert_and_scroll(part, 'code_block' if self.in_code_block else 'ai_response')
        else:
            tag = 'code_block' if self.in_code_block else 'ai_response'

            self.current_ai_response += chunk
            self._insert_and_scroll(chunk, tag)

            if not self.in_code_block and '**' in chunk:
                self._apply_bold_tags()

        self.output_text.config(state='disabled')

    def _apply_bold_tags(self):
        text_content = self.output_text.get("1.0", tk.END)
        self.output_text.tag_remove('bold', "1.0", tk.END)

        for match in re.finditer(r'\*\*(.*?)\*\*', text_content, re.DOTALL):
            start_pos = match.start(1)
            end_pos = match.end(1)

            start_index = self.output_text.index(f"1.0 + {start_pos} chars")
            end_index = self.output_text.index(f"1.0 + {end_pos} chars")

            self.output_text.tag_add('bold', start_index, end_index)

    def _insert_and_scroll(self, text, tag=None):
        self.output_text.insert(tk.END, text, tag)
        self.output_text.see(tk.END)

    def _append_simple_text(self, text, tag=None):
        self.output_text.config(state='normal')
        self.output_text.insert(tk.END, text, tag)
        self.output_text.see(tk.END)
        self.output_text.config(state='disabled')

    def _enable_input(self):
        self.input_entry.config(state='normal')
        self.send_button.config(state='normal')
        self.continuous_checkbox.config(state='normal')  # 启用复选框
        self.input_entry.focus_set()


if __name__ == '__main__':
    root = tk.Tk()
    app = AIChatApp(root)
    root.geometry("800x1000")
    root.mainloop()