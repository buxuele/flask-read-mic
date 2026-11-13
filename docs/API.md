# 局域网语音识别 API

把本机运行的 Qwen3-ASR 模型开放给同一局域网内的其他设备调用，包括 Mac、iPhone、Android、另一台 Windows 电脑、脚本和自动化工具。

服务随主程序自动启动，独立监听 `0.0.0.0:6101`，与网页服务共用同一份已加载模型，不会额外占用显存。

## 适用场景

1. 在 Mac 上用命令行或脚本调用本机识别。
2. 手机录完音直接上传，拿到文字。
3. 局域网内的其他服务把音频转文字，例如笔记工具、自动化流程、监控脚本。
4. 多台设备共用一个模型，不必每台都装 GPU。

前提条件：

1. 主机与其他设备在同一网段，通常指连接同一个路由器或同一个 Wi-Fi。
2. 主机保持开机，`just_run.bat` 保持运行。
3. 主机防火墙允许 6101 端口入站。
4. 其他设备能访问主机的局域网 IP，不能是 127.0.0.1。

跨网段、公司网络隔离、访客 Wi-Fi 通常无法直连，需要网络管理员放行或改用内网穿透。

## 一、主机侧准备

### 1. 启动服务

以管理员身份双击 `just_run.bat`。启动完成后终端会显示：

```
  语音转录
  ──────────────────────────────────────────
  服务    http://127.0.0.1:6100
  内网    http://192.168.0.107:6101/api/v1
  密钥    q18FKS-eF8yxLRRrkB6UpZYQclzDKLmd
  模型    就绪

  ──────────────────────────────────────────
  双击 Ctrl 说话    Ctrl+C 退出
```

记下 `内网` 这一行的地址和 `密钥`。其他设备就用这两个值。

如果内网地址显示 127.0.0.1 或明显不是局域网 IP，说明主机同时开了 VPN、虚拟网卡或热点。先用 `ipconfig` 找到真实网卡地址，例如 `192.168.x.x` 或 `10.x.x.x`。

### 2. 确认监听状态

在主机上执行：

```powershell
Get-NetTCPConnection -LocalPort 6101 -State Listen
```

能看到 `0.0.0.0:6101` 或 `127.0.0.1:6101` 即表示服务在监听。如果是 `127.0.0.1`，其他机器访问不到，需要检查 `LAN_API_HOST` 配置。

### 3. 放行防火墙

第一次启动时 Windows 可能弹出防火墙提示，勾选专用网络并允许。

如果没有弹出，以管理员身份打开 PowerShell 执行：

```powershell
New-NetFirewallRule -DisplayName "ASR LAN API" -Direction Inbound -Protocol TCP -LocalPort 6101 -Action Allow -Profile Private
```

只对专用网络放行，不要对公用网络开放。不再使用时删除规则：

```powershell
Remove-NetFirewallRule -DisplayName "ASR LAN API"
```

### 4. 建议固定主机 IP

路由器默认用 DHCP 分配地址，重启后 IP 可能变化，客户端配置就会失效。

两种做法：

1. 在路由器后台给主机网卡绑定固定 IP。
2. 在 Windows 网卡设置里配置静态 IP。

固定后把地址写进客户端配置，以后不用每次改。

### 5. 密钥

密钥优先级：

1. 环境变量 `ASR_API_KEY`。
2. 文件 `src/recordings/.lan_api_key`，首次启动自动生成。
3. 都没有时自动生成并写入上述文件。

查看当前密钥：

```powershell
Get-Content src\recordings\.lan_api_key
```

固定密钥：在启动前设置环境变量 `ASR_API_KEY`，或在 `.env` 中写入同名变量。

### 6. 关闭局域网 API

不需要时设置环境变量 `ASR_LAN_API=0` 再启动，6101 端口不会监听。

## 二、客户端接入

### 通用约定

1. 基础地址：`http://主机IP:6101/api/v1`，端口以启动器打印为准。
2. 鉴权：请求头 `X-API-Key: 你的密钥`，或 `Authorization: Bearer 你的密钥`。
3. 请求格式：`multipart/form-data`。
4. 音频字段名必须是 `audio`。
5. 支持格式：wav、webm、mp3、m4a、ogg、flac。采样率和声道不限，服务端会转成 16kHz 单声道。
6. 单次音频不超过 300 秒，请求体不超过 25MB。
7. 语言字段可选：`zh`、`en`、`auto`，默认 `auto`。
8. 上下文提示可选：`context`，最多 1000 字，用于提升专有名词准确率。

### Mac

先测连通性：

```bash
curl http://192.168.0.107:6101/api/v1/health \
  -H "X-API-Key: 你的密钥"
```

正常返回类似：

```json
{"status":"ok","model":"Qwen3-ASR-0.6B","device":"cuda:0","torch":"2.11.0+cu128","languages":["zh","en","auto"],"max_seconds":300}
```

再上传音频：

```bash
curl -X POST http://192.168.0.107:6101/api/v1/transcribe \
  -H "X-API-Key: 你的密钥" \
  -F "audio=@录音.m4a" \
  -F "language=zh"
```

Python 调用：

```python
import requests

with open("录音.m4a", "rb") as f:
    r = requests.post(
        "http://192.168.0.107:6101/api/v1/transcribe",
        headers={"X-API-Key": "你的密钥"},
        files={"audio": ("录音.m4a", f, "audio/mp4")},
        data={"language": "zh", "context": "讨论新能源汽车行业"},
        timeout=180,
    )
print(r.json()["text"])
```

Shell 脚本里批量处理：

```bash
for f in *.m4a; do
  echo -n "$f: "
  curl -s -X POST http://192.168.0.107:6101/api/v1/transcribe \
    -H "X-API-Key: 你的密钥" \
    -F "audio=@$f" -F "language=zh" | python3 -c "import sys,json;print(json.load(sys.stdin)['text'])"
done
```

### iPhone

系统自带语音备忘录录音格式是 m4a，可以直接上传。

使用快捷指令：

1. 打开快捷指令，新建一个快捷指令。
2. 添加操作「获取 URL 内容」。
3. URL 填 `http://192.168.0.107:6101/api/v1/transcribe`。
4. 展开更多选项，方法选 POST。
5. 请求头添加一项，键为 `X-API-Key`，值为你的密钥。
6. 请求体选表单。
7. 添加表单字段，键为 `audio`，类型选文件，值为要上传的录音。
8. 需要固定语言时再加一个字段，键为 `language`，值为 `zh`。
9. 运行后，用「获取字典值」取出 `text` 字段即可得到文字。

不同 iOS 版本菜单名称可能略有差异，核心是四件事：POST、地址、请求头、表单字段 audio。

注意：iOS 对非 HTTPS 请求默认有限制，同一 Wi-Fi 下的局域网地址通常可以直接访问。如果快捷指令提示不安全连接，改用支持自定义 HTTP 的第三方 App，或者在本机加一层 HTTPS 反向代理。

### Android

任意支持 multipart 上传的 HTTP 客户端都可以，参数与上面一致：

1. 方法 POST。
2. URL `http://192.168.0.107:6101/api/v1/transcribe`。
3. 请求头 `X-API-Key`。
4. 表单字段 `audio`，类型文件。
5. 可选字段 `language`。

装了 Termux 可以直接用 curl：

```bash
curl -X POST http://192.168.0.107:6101/api/v1/transcribe \
  -H "X-API-Key: 你的密钥" \
  -F "audio=@/sdcard/录音.m4a" -F "language=zh"
```

### 浏览器端

服务默认开启 CORS，手机或电脑浏览器里的网页可以直接跨域调用。

```javascript
const form = new FormData();
form.append('audio', file);          // file 来自 input[type=file] 或录音 Blob
form.append('language', 'zh');

const res = await fetch('http://192.168.0.107:6101/api/v1/transcribe', {
  method: 'POST',
  headers: { 'X-API-Key': '你的密钥' },
  body: form
});
const data = await res.json();
console.log(data.text);
```

浏览器调用需要 HTTPS 的场景仅限页面本身是 HTTPS 时。局域网内用 `http://` 页面调用 `http://` 接口不存在混合内容问题。

### Node.js

```javascript
import fs from 'node:fs';

const form = new FormData();
form.append('audio', new Blob([fs.readFileSync('录音.m4a')]), '录音.m4a');
form.append('language', 'zh');

const res = await fetch('http://192.168.0.107:6101/api/v1/transcribe', {
  method: 'POST',
  headers: { 'X-API-Key': '你的密钥' },
  body: form
});
console.log((await res.json()).text);
```

### PowerShell

以下命令需要 PowerShell 7 及以上，Windows 自带的 5.1 不支持 `-Form` 参数，请改用上面的 curl。

```powershell
$form = @{
    audio    = Get-Item "C:\录音.m4a"
    language = "zh"
}
Invoke-RestMethod -Uri "http://192.168.0.107:6101/api/v1/transcribe" `
    -Method Post -Headers @{ "X-API-Key" = "你的密钥" } -Form $form
```

## 三、验证顺序

按这个顺序排查，能快速定位问题在哪一层：

1. 主机上访问 `http://127.0.0.1:6101/api/v1/health`，确认服务本身正常。
2. 主机上用局域网 IP 访问同一个地址，确认绑定在 0.0.0.0。
3. 另一台设备 ping 主机 IP，确认网络可达。
4. 另一台设备访问 health，确认防火墙和端口放行。
5. 最后再上传音频，确认业务流程。

任何一步失败，问题就在那一步之前，不用继续往下试。

## 四、常见问题

| 现象 | 常见原因 | 处理 |
|---|---|---|
| 连接被拒绝 | 服务未启动，或只监听 127.0.0.1 | 检查 `Get-NetTCPConnection -LocalPort 6101`，确认服务在跑 |
| 连接超时 | 防火墙拦截，或不同网段 | 放行 6101，确认设备在同一路由器下 |
| 401 | 密钥错误或缺失 | 核对请求头，注意不要带多余空格 |
| 400 音频解码失败 | 格式不支持或文件损坏 | 换成 wav 或 m4a 再试 |
| 400 音频太短 | 小于 0.1 秒 | 检查录音是否为空 |
| 413 | 音频超过 300 秒 | 切分成多段分别上传 |
| 429 | 超过每分钟 30 次 | 降低频率，等待一分钟 |
| 返回文本为空 | 音频是静音或纯噪声 | 换一段有说话的音频 |
| 手机能 ping 通但接口不通 | 热点隔离或访客网络 | 关闭路由器的 AP 隔离，或换到主网络 |

查看主机日志：

```
src/logs/app_*.log
src/logs/transcribe_*.log
```

## 五、安全注意

1. 服务没有 TLS，请求和密钥都是明文。只在可信内网使用。
2. 不要把 6101 端口映射到公网，也不要放进 DMZ。
3. 密钥泄露后立即修改：删除 `src/recordings/.lan_api_key`，重新启动即可生成新密钥。
4. 不需要时用 `ASR_LAN_API=0` 关闭，端口完全不监听。
5. 只对专用网络放行防火墙规则，不要对公用网络开放。

## 六、性能与并发

单次推理约 1.1 秒，具体取决于音频长度和显卡性能。

当前定位单人使用。多个客户端同时请求时会排队，但不是显式队列，而是线程阻塞在推理锁上。实测三个客户端同时上传 4.2 秒音频，分别耗时 1.14 秒、1.78 秒、2.41 秒，总墙钟 2.62 秒。

限制：

1. 没有队列长度上限。
2. 没有等待超时。
3. 不保证先到先服务。
4. 客户端断开后请求仍会执行完。

多人并发需要改成有界队列，队列满返回 429，等待超时返回 503；或者改用 vLLM 批处理后端。

## 七、接口参考

### POST /api/v1/transcribe

请求字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `audio` | 是 | 音频文件，支持 wav、webm、mp3、m4a、ogg、flac |
| `language` | 否 | `zh`、`en`、`auto`，默认 `auto` |
| `context` | 否 | 前文提示，最多 1000 字 |

成功响应：

```json
{
  "text": "甚至出现交易几乎停滞的情况。",
  "language": "zh",
  "duration": 4.2,
  "model": "Qwen3-ASR-0.6B"
}
```

字段说明：

1. `text` 是识别文本，简体输出。
2. `language` 是请求时指定的语言。
3. `duration` 是音频时长，单位秒。
4. `model` 是当前加载的模型路径或名称。

错误响应统一为：

```json
{"error": "错误说明"}
```

状态码：

| 状态码 | 含义 |
|---|---|
| 400 | 参数错误、音频无法解码、音频太短 |
| 401 | 密钥缺失或错误 |
| 413 | 音频超过 300 秒 |
| 429 | 超过每分钟 30 次 |
| 500 | 识别过程异常 |

### GET /api/v1/health

需要同样的鉴权。返回示例：

```json
{
  "status": "ok",
  "model": "Qwen3-ASR-0.6B",
  "device": "cuda:0",
  "torch": "2.11.0+cu128",
  "languages": ["zh", "en", "auto"],
  "max_seconds": 300
}
```

`device` 为 `cpu` 时表示没有检测到 CUDA，识别会明显变慢。
