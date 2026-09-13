# VPet 参考记录

用户于 2026-09-13 提供 [LorisYounger/VPet](https://github.com/LorisYounger/VPet) 并要求参考吸纳。读取 main，当时 HEAD 为 fd1265bf8c4930c3fbd03b210d8dbd28a3567d2d。

本目录保存只读源码参考及原项目 LICENSE；这些 C# 文件未编译或接入桌宠运行。我们的 Python 实现根据任务需求独立编写。

## 已吸收

- MainDisplay.cs 中的 A_Start → B_Loop → C_End 思路：动作明确进入、持续、收尾。
- 按住提起与松手退出相分离，动作优先级避免在空中误开其他动作。
- GraphInfo.cs 中动作类型、动画名、阶段与人物状态分开；本工程也把交互状态、素材参数、身份数据分开。
- PNGAnimation.cs 是序列帧播放器：丰富动作可以依赖绘制的动作帧。将来大幅挥手、坐下等，优先专门制作姿势或绑定，不能靠把整张立绘摇动冒充。

## 没有直接采用

VPet 核心适合 WPF；用户明确还要 Mac，因此不移植其 Windows 界面框架。也没有复制其自带角色动画到静香。官方将代码 Apache-2.0 和自带动画授权分开描述；本目录保留代码 LICENSE，动画按官方单独说明处理。

来源：

- [动作流程](https://github.com/LorisYounger/VPet/blob/fd1265bf8c4930c3fbd03b210d8dbd28a3567d2d/VPet-Simulator.Core/Display/MainDisplay.cs)
- [图形元数据](https://github.com/LorisYounger/VPet/blob/fd1265bf8c4930c3fbd03b210d8dbd28a3567d2d/VPet-Simulator.Core/Graph/GraphInfo.cs)
- [PNG 动画](https://github.com/LorisYounger/VPet/blob/fd1265bf8c4930c3fbd03b210d8dbd28a3567d2d/VPet-Simulator.Core/Graph/PNGAnimation.cs)
- [许可与动画说明](https://github.com/LorisYounger/VPet#动画版权声明与授权)
