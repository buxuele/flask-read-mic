# macOS 客户端

1. brew install portaudio
2. cp .env.example .env，填入服务端地址与密钥
3. ./just_run.sh

按住 Ctrl 说话，松开后文字自动粘贴到光标处。

## 简介

菜单栏听写工具。录音在本机做，识别交给局域网里的 flask-read-mic 服务端，结果直接粘贴到当前焦点输入框，浏览器、笔记、终端都能用。

## 功能

1. 按住 Ctrl 录音，停顿 0.6 秒切一句，切出立刻上传，不用等整段说完。
2. 三路并发上传，结果按说话顺序粘贴；连接复用，不反复握手。
3. 每句带上一句的识别结果作为前文提示，专有名词更准。
4. Ctrl 加其他键不触发，Ctrl+C、Ctrl+V 照常用。
5. 菜单栏图标显示状态：空闲麦克风、录音红色麦克风加秒数、识别中省略号、出错橙色感叹号。
6. 菜单里能看接口连通性、麦克风与辅助功能权限、最近一条识别结果，可一键复制。
7. 菜单里能切换麦克风和识别语言，选择写回 .env。
8. 上传前裁掉首尾静音；录音最长 280 秒自动结束。
9. 录音过短、没有声音、接口报错、识别为空都不粘贴。
10. 粘贴后恢复原剪贴板，期间你复制了新内容就不覆盖。
11. 网络断开或超时自动重试一次。

## 服务端

需要同一局域网里运行 flask-read-mic，默认监听 6101，密钥在服务端启动时打印。接口协议见仓库 docs/API.md。

客户端只调用三个地址：

1. GET /api/v1/health，启动与打开菜单时检查连通性。
2. POST /api/v1/transcribe，上传 16kHz 单声道 wav，返回 text。
3. 其余接口不涉及。

## 配置

配置写在 client/.env，参考 .env.example。

| 变量 | 说明 |
|---|---|
| ASR_URL | 服务端地址，例如 http://192.168.0.104:6101/api/v1 |
| ASR_KEY | 服务密钥 |
| LANGUAGE | zh、en、auto，默认 zh |
| MIC_DEVICE | 麦克风名称片段或序号，留空用系统默认 |
| MIN_RMS | 音量门限，低于该值视为没说话，默认 40 |
| CHUNK_THRESHOLD | 断句振幅门限，超过视为说话，默认 500 |
| CHUNK_SILENCE | 停顿多少秒算一句结束，默认 0.6 |

## 权限

1. 麦克风：首次启动会弹窗，允许即可。
2. 辅助功能：系统设置 → 隐私与安全性 → 辅助功能，给运行脚本的终端 App 打勾。没有这项，Ctrl 不响应，也粘贴不出去。
3. 菜单里能直接查看两项权限状态，也能跳到设置页。

## 开发

1. 运行：just_run.sh 会创建 .venv、装依赖、启动菜单栏进程，终端保持占用。
2. 测试：全部用合成音频，不占用麦克风和扬声器。

```
.venv/bin/python tests/test_controller.py
.venv/bin/python tests/test_segmenter.py
.venv/bin/python tests/test_stream.py
.venv/bin/python tests/test_asr.py
.venv/bin/python tests/test_clipboard.py
.venv/bin/python tests/test_paste.py
.venv/bin/python tests/test_retry.py
.venv/bin/python tests/test_config.py
.venv/bin/python tests/test_recorder.py
```

3. 日志在 client/logs/app.log，菜单里能直接打开。
