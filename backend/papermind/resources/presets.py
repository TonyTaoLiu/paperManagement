"""Built-in starter taxonomy (docs/项目开发文档.md Appendix A). Users can edit it freely."""

# (name, description, [(child name, child description)])
NEURO_PRESET = [
    ("PD 病理电生理与 beta 动力学", "频谱特征与症状关联、beta burst 与网络时序、beta 生成机制建模", [
        ("频谱特征与症状关联", "STN-LFP/皮层频谱特征与运动症状（少动、僵直、震颤）的多变量关联"),
        ("beta burst 与网络时序", "beta burst 的时长/幅度/同步，以及跨脑区的时间先后与网络级联"),
        ("beta 生成机制建模", "用 Wilson–Cowan、发放率或脉冲网络模型研究 beta 振荡的产生回路与机制"),
    ]),
    ("Aperiodic（1/f）神经活动", "非周期（1/f）频谱成分、specparam/FOOOF、aperiodic exponent/offset/knee", []),
    ("睡眠与状态感知神经调控", "睡眠分期、spindle、sleep-wake 状态对神经信号与刺激的影响", []),
    ("步态 / 冻结步态（FOG）", "帕金森步态障碍、冻结步态、步态适应与相关神经机制", []),
    ("自适应 / 闭环神经调控工程", "aDBS、闭环刺激、tACS、传感与控制器设计、设备部署", []),
    ("DBS 疗效预测与影像机制", "基于影像或连接组预测 DBS 疗效与机制", []),
    ("AI 与计算方法学", "表征分析、生成模型、神经动力学反演、预训练模型等 AI/计算方法", []),
    ("数据资源与科研工具", "公开数据集、数据资源、科研工作流与自动化工具", []),
]  # fmt: skip
