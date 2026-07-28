# 遥控器中心 Remote Bridge Hub（上游原始说明）

> [!IMPORTANT]
> ### 2655智充 · AI 会员自助充值中心
>
> ChatGPT Plus / Pro、Grok 等 AI 会员自助充值，在线下单，自动发货。
>
> **[立即访问 2655AI.com →](https://2655ai.com)**

一个仓库，三套可独立安装的 Windows 硬件桥接程序。源码共享底层能力，发行时互不捆绑。

## 三套独立程序

- **Xiaomi Remote Bridge**：小米蓝牙遥控器 2 Pro / RC003 的按键映射、长按连续动作和 ATVV 蓝牙语音桥接。
- **T1 Remote Bridge**：T1 谷歌遥控器的原生空中飞鼠、语音键、翻页和自定义按键。
- **V60 Pen Bridge**：汉王 V60 / PV60 的原生空中飞鼠、HID 麦克风会话和三个笔键映射。

支持 64 位 Windows 10 1809 及以上版本。T1 和 V60 使用设备接收器自带的麦克风；小米遥控器的蓝牙语音链路需要 VB-CABLE。

## 下载

普通用户从 [GitHub Releases](https://github.com/xxb26553663-star/remote-bridge-hub/releases) 选择自己的设备，只安装其中一个包：

- `XiaomiRemoteBridgeSetup-1.0.0.exe`
- `T1RemoteBridgeSetup-1.0.0.exe`
- `V60PenBridgeSetup-1.0.0.exe`

三套程序有各自的配置目录、进程入口、端口和卸载项，不要求安装统一中心。

## 仓库结构

```text
source/standalone/          三套独立入口
source/bridges/xiaomi/      小米桥接
source/bridges/t1/          T1 桥接
source/bridges/hanvon/      V60 / PV60 桥接
source/bridges/audio/       小米虚拟音频路由
delivery/standalone/setup/  三套 Inno Setup 安装器
scripts/                    第三方资源获取和公开边界检查
tests/                      自动化测试
```

`source/remote_bridge_hub.py` 是可选的统一中心入口；三套 Release 安装包不依赖它。

## 从源码运行

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

python .\source\standalone\xiaomi_main.py
python .\source\standalone\t1_main.py
python .\source\standalone\v60_main.py
```

首次使用前，先在 Windows 中配对或插入对应设备。小米桥接会自动发现已配对的 2 Pro，也可在设置里填写蓝牙地址，例如 `AA:BB:CC:DD:EE:FF`。仓库不内置任何用户设备地址。

## 构建三套安装包

先安装 Python 依赖和 Inno Setup 6，然后运行：

```powershell
python -m pip install -r requirements-dev.txt
.\delivery\build-standalone-packages.ps1 -Version 1.0.0 -AllowUnsignedCandidate
```

构建脚本会从官方地址获取 Frida Gadget 和 VB-CABLE，并在使用前校验固定 SHA-256。它还会检查源码边界、运行全部测试、逐包检查归档内容，再生成三个安装器。自定义工具位置可使用 `-PythonExecutable` 和 `-InnoCompilerPath`。

商品照片因缺少清晰的再分发授权，不进入仓库或官方构建。照片缺失只会让小米按键页显示资源提示，不影响桥接功能。

## 第三方组件

小米包使用 Frida Gadget 读取 Windows 普通输入链路拿不到的 RC003 返回键 HID 报告；这不是授权或防破译组件。小米安装器还包含 VB-Audio 官方的 VB-CABLE 驱动包，并保留其 Donationware 来源说明。详情、版本、来源和校验值见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 公开边界

公开仓库只包含硬件桥接、安装器源码、测试和文档，不包含收费授权、设备绑定、防破译构建、客户数据、云端服务或付款系统代码。提交前运行：

```powershell
.\scripts\check-public-boundary.ps1
```

该检查也会阻止真实设备地址、个人绝对路径、凭据和第三方二进制被提交。

## 参与贡献

贡献代码前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

## 开源协议

项目代码使用 [GPL-3.0](LICENSE) 发布。第三方组件继续适用各自协议；`2655 AI` 名称、Logo 和品牌资产不包含在 GPL 授权中。
