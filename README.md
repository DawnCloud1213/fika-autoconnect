# Fika AutoConnect — SPT 联机自动填 IP 工具

## 这是干嘛的
用「汽游」等虚拟局域网联机 Fika（SPT）时，主机 IP 每次都会变。
双击本工具，它自动：
1. 检测汽游虚拟网卡（QIYOU_PLAY）是否在线
2. 扫网段内开 6969 端口的主机（谁开服就扫到谁）
3. 把主机 IP 写进 SPT Launcher 的 LauncherSettings.json（更新 JR 条目）
4. 自动启动 SPT Launcher，直接连接

## 本机使用
1. 先开「汽游」并进入房间（本机拿到 10.26.0.x 地址）
2. 双击 `fika_autoconnect.bat`（或桌面快捷方式「SPT联机启动」）
3. 等 Launcher 自动打开，直接连即可

## 换电脑部署（3 步）
1. 把整个文件夹（fika_autoconnect.py + config.json + 本 README）复制到新电脑任意位置
2. 改 `config.json`：
   - `spt_root`：改成新电脑 SPT 安装目录（含 SPT_Runtime 的那层）
   - `server_entry_name`：改成你 Launcher 里「服务器」下拉框中的名字（默认 JR）
   - （可选）`vlan_adapter_keyword`：汽游是 QIYOU_PLAY，别的虚拟网卡改这里
3. 双击 `fika_autoconnect.bat` 即可。也可以右键建快捷方式放桌面。

> 如果 `spt_root` 留空，脚本会自动探测常见位置（D:\free games\EFT* 等）。
> 新电脑没有 Python？装个 Python 3.11+ 即可（或改 bat 里的 pythonw 路径）。

## 配置项说明
| 字段 | 默认 | 说明 |
|------|------|------|
| spt_root | 自动探测 | SPT 根目录（含 SPT_Runtime） |
| server_entry_name | JR | Launcher 服务器条目名 |
| vlan_adapter_keyword | QIYOU_PLAY | 虚拟网卡关键字 |
| spt_port | 6969 | SPT 服务端口 |
| launch_launcher | true | 是否自动启动 Launcher |
| scan_concurrency | 120 | 扫描并发数 |
| scan_timeout | 0.35 | 单 IP 超时(秒) |

## 排障
- 日志在 `<spt_root>\SPT_Runtime\user\sptappdata\fika_autoconnect_logs\fika_autoconnect.log`
- 提示「没检测到 SPT 主机」：确认主机已开 SPT.Server.exe、且你在同一汽游房间
- 提示「未检测到汽游虚拟网卡」：先开汽游进房间再跑
