# Fika AutoConnect — SPT 联机自动填 IP 工具

## 这是干嘛的
用「汽游」等虚拟局域网联机 Fika（SPT）时，主机 IP 每次都会变。
双击它，自动：扫汽游网段内开 6969 的主机 → 填进 Launcher 的 JR 条目 → 启动 Launcher。

## 部署位置（重要）
脚本必须放在 **SPT 游戏根目录下新建的 `FikaAutoConnect` 文件夹**里：

```
D:\free games\EFT_0821\              ← SPT 根（含 SPT_Runtime、EscapeFromTarkov.exe）
├── SPT_Runtime\
├── EscapeFromTarkov.exe
└── FikaAutoConnect\                  ← 本工具放这里（新建文件夹）
    ├── fika_autoconnect.py
    ├── fika_autoconnect.bat
    └── config.json
```

**为什么**：脚本用「自身位置上一级」自动推导 SPT 根，不需要配置、不需要探测安装位置。
搬运 = 整个游戏目录拷走即可，工具跟着走，天然不分离。

## 本机使用
1. 开「汽游」并进入房间
2. 双击 `FikaAutoConnect\fika_autoconnect.bat`（或桌面「SPT联机启动」快捷方式）
3. Launcher 自动打开，直接连

## 换电脑部署（零配置）
整个 `FikaAutoConnect` 文件夹复制到新电脑的 SPT 游戏根目录下（和 `SPT_Runtime` 平级），
双击 bat 即可。脚本位置自动推导，什么都不用改。

## 配置项说明（config.json，一般不用动）
| 字段 | 默认 | 说明 |
|------|------|------|
| server_entry_name | JR | Launcher 服务器条目名（下拉框里的名字） |
| vlan_adapter_keyword | QIYOU_PLAY | 虚拟网卡关键字（非汽游工具改这里） |
| spt_port | 6969 | SPT 服务端口 |
| launch_launcher | true | 是否自动启动 Launcher |
| scan_concurrency | 120 | 扫描并发数 |
| scan_timeout | 0.35 | 单 IP 超时(秒) |

## 排障
- 日志在 `<SPT根>\SPT_Runtime\user\sptappdata\fika_autoconnect_logs\fika_autoconnect.log`
- 提示「没检测到 SPT 主机」：确认主机已开 SPT.Server.exe、且在同一汽游房间
- 提示「未检测到汽游虚拟网卡」：先开汽游进房间再跑
