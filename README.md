# 制糖工厂小电拼的Home Assistant集成<br>CoCan Integration for Home Assistant

[![HACS Badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

[English](#english) | [简体中文](#chinese)

---

<a name="chinese"></a>
## 💡 核心优势：App 无缝共存 和 无局域网限制

1️⃣ 制糖工厂小电拼 自带 MQTT 接入功能，但启用 MQTT 会导致官方 App 失效。本集成**基于制糖工厂为 AI 智能体开放的 MCP 协议**开发，无需占用 MQTT 协议❗️

   | 接入方式 | 官方 App | Home Assistant | 特点 |
   | :--- | :---: | :---: | :--- |
   | **MQTT 接入** | ❌/✅ | ✅/❌ | app 与 HA 二选一 |
   | **MCP (本集成)** | ✅ | ✅ | **双端共存，互不干扰** |

 <br>2️⃣ mcp 协议传输使用制糖工厂官方服务器， **无需** 小电拼和 Home Assistant 在同一局域网下‼️<br>❇️ **无论小电拼在全球任意位置，联网即可控制** ❇️

---

## ⚡ 快速开始

### 方式一：HACS 安装（推荐）
1. 导航至 **HACS** -> 右上角菜单 -> **自定义存储库**。
2. 添加仓库 `https://github.com/Adisonyao/HA_mcp_CoCan`，类别选择 **集成 (Integration)**。
3. 搜索 **MCP Device** 并安装，随后重启 Home Assistant。
4. 在 **设置 -> 设备与服务** 中添加集成 **MCP Device**。

### 方式二：手动安装
1. 下载最新 [Release](https://github.com/Adisonyao/HA_mcp_CoCan/releases) 压缩包。
2. 解压获得 **"mcp_cocan"文件** ，并将文件夹移至你的Home Assistant配置目录 `/config/custom_components/mcp_cocan/`。
3. 重启 Home Assistant。
4. 在 **添加集成** 页面搜索 **"小电拼Home Assistant"** 添加集成。

---

## ⚙️ 配置参数

| 参数 | 示例 | 说明 |
| :--- | :--- | :--- |
| **MCP Server 地址** | `https://mcp.thecandysign.com/xxx/xxx/mcp` | 从小电拼 App 获取的完整 MCP 地址 |
| **传输类型** | `Streamable HTTP` | 默认传输协议 |
| **认证 Token** | *（留空）* | 若服务端未开启 Token 认证则留空 |
| **设备名称** | `小电拼 Pro` | 自定义显示名称 |
| **轮询间隔** | `15` 秒 | 状态同步频率 (范围: 5–300s) |

### 📖 如何获取 MCP Server 地址？

1. 打开 **小电拼小程序 / App**。
2. 进入 **设置** -> **龙虾服务**-> **下拉菜单改成"其他"**。
3. 复制页面中的完整 Prompt 文本（格式如下）：
   > “现在安装控制「AI小电拼 Mirror」的技能：阅读'https://mcp.thecandysign.com/1340********3233/SKILL.md'。这台小电拼的名字是「小电拼 3233」。MCP 服务器的地址是'**https://mcp.thecandysign.com/1340********3233/********/mcp**'。”
4. 从中提取出 `'` 单引号包裹的 **MCP 服务器地址**（即以 `https://.../mcp` 结尾的部分），复制填入 Home Assistant 集成配置项中。

---

## 🔌 硬件与端口映射

支持 **制糖工厂 小电拼 (CP-02S/CP-02)**（160W 总功率）

| HA 显示名称 | MCP 索引 | 物理接口 | 接口最大功率 |
| :--- | :---: | :---: | :---: |
| **Port A** | port 1 | USB-A | 60W |
| **Port C1 ~ C4** | port 2 ~ 5 | USB-C | 140W |

---

## 📊 实体支持 (共 152 个实体)

本集成提供极其丰富的设备监控与控制能力，实体分为**控制类实体**与**状态类实体**：

<details>
<summary>👉 点击展开：单端口实体列表 (5 端口 × 24 个)</summary>
<ul>


   #### 🎛️ 控制类实体 (Per Port)
   * **端口充电开关** (`switch`)：开启/关闭指定端口充电
   * **功率分配上限** (`number`)：各端口最大输出功率滑块 (Port A: 0-60W, Port C1-C4: 0-140W)

   #### 📈 状态类实体 (Per Port)
   * **基础监控**：实时功率 (W)、输出电压 (V)、输出电流 (A)、端口温度、设备接入状态、快充协议 (PD/非快充)
   * **链路与物理状态**：工作电压/电流、PD 温度、PDO ID、USB 最高速度、双角色电源、电池检测与电量 (%)、PD 协商功率、输入端电压
   * **PD 与线缆信息**：PD 连接设备名称/品牌、连接线缆名称/品牌/最大支持电压/E-Marker 芯片/主动线缆标识
   * **数据统计**：会话累计电量 (mWh)
</ul>
</details>

<details>
<summary>👉 点击展开：设备级实体列表 (7 个)</summary>
<ul>

#### 🎛️ 控制类实体 (Device Level)
* **充电策略** (`select`)：切换充电模式 (FAST自由流 / SLOW均衡 / 小家电 / 高性能 / 单口极速)
* **温度模式** (`select`)：性能优先 / 温控优先
* **屏幕控制** (`select`)：显示亮度 (关/低/中/高)、屏显模式 (待机动画优先/功率优先)、待机动画选择 (流星/落花/康威生命游戏/时间)
* **系统功能** (`switch`)：整点报时开关

#### 📈 状态类实体 (Device Level)
* **设备与硬件信息**：产品型号 (`CP-02S`/`CP-02`)、最大功率预算 (`160W`)、固件版本 (FPGA + App 双版本)、设备序列号 (PSN)
* **网络传感器**：WiFi SSID / BSSID / Channel / Protocol / RSSI 信号强度 (dBm)
* **总揽传感器**：5 端口总实时功率 (W)、5 端口总分配功率 (W)
</ul>
</details>

---

## 🛠️ 项目结构与数据流

<details>
<summary>👉 点击展开：代码架构与安全设计</summary>
<ul>

```
custom_components/mcp_cocan/
├── __init__.py          # 集成入口与平台注册
├── config_flow.py       # UI 配置与连接测试流程
├── coordinator.py       # 数据协调器 (轮询 MCP & 状态缓存)
├── mcp_client.py        # 原生 JSON-RPC over HTTP 客户端 (零第三方依赖)
├── entity.py            # 实体基类与字段解析
├── default_config.py    # 152 个默认实体的配置模板
└── sensor.py / switch.py / select.py / number.py  # 各平台实现
```

#### 安全设计 (Security Guidelines)
- **SSRF 防御**：严格限制 HTTP/HTTPS 协议，拒绝 Loopback 与 Link-Local 地址。
- **资源限制**：限制单次响应大小 (1MB) 与 JSON 路径嵌套深度 (Max 20)，防止拒绝服务攻击。
- **输入校验**：使用工具白名单，限制 Select 选项枚举，强类型转换数值传感器。
</ul>
</details>

---

## ❓ 常见问题 (FAQ)

**Q: 为什么充电策略设置后在 HA 中不更新？**
> **A:** 受限于 MCP 协议，服务器未公开策略读取 API，仅支持写入。通过外部修改策略后 HA 无法主动获取最新状态。

**Q: 部分 PD 传感器显示 `unknown`？**
> **A:** `get_port_pd_status` 仅返回当前有设备连接的活跃端口。空闲端口显示 `unknown` 属于正常现象。

**Q: 调整功率分配滑块后没有生效？**
> **A:** 接口要求 5 个端口同步发送且**总和不得超过 160W**。若超出限制，请求会被拒绝并自动弹回原值。



---

## 📄 License

本项目基于 [GNU General Public License v3.0](LICENSE) 开源。*本集成属于第三方开源插件，与 CANDYSIGN（制糖工厂）官方无关。*

---
---

<a name="english"></a>
## English Quick Overview

### Core Advantage: App Coexistence
This integration leverages the **MCP Protocol** open for AI agents. Unlike MQTT, it allows the **Official App and Home Assistant to run simultaneously** without conflict.

### Installation & Configuration
1. Install via **HACS** (Custom Repository) or manually copy to `/config/custom_components/mcp_cocan/`.
2. Retrieve your MCP Server URL (`https://.../mcp`) from the official App under **Settings -> Lobster Service**.
3. Add **MCP Device** in HA Integration settings and enter the MCP Server URL.

### Features
* **Full Hardware Support**: Port A (60W) + Port C1-C4 (140W), max 160W total budget.
* **152 Entities (Control & State)**: Separated into control entities (switches, sliders, screen/strategy select) and state sensors (power, voltage, PD protocols, cable details, WiFi status).
* **Zero External Dependencies**: Pure Python JSON-RPC HTTP client implementation with builtin SSRF and Memory security guards.

### License
Distributed under the **GPL-3.0 License**. See [LICENSE](LICENSE) for details.
