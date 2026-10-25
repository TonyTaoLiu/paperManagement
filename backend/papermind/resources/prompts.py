"""Improved paper-summary prompt (docs Appendix B) that ends with a machine-readable YAML block."""

IMPROVED_PROMPT = """你是一名经验丰富的计算神经科学家。请仔细阅读全文（如果无法访问全文，请明确说明你实际读到了哪些部分，不要猜测），然后总结：

1. 研究背景和科学问题；
2. 研究方法和数据集（样本量、模态、设备、数据来源、标注方式/ground truth）；
3. 重要结果和对应的结论（给出关键数字，并注明出自哪个图/表/章节）；
4. 作者/团队信息，以及该团队可能相关的前置或后续工作；
5. 你对这篇论文的思考：优缺点、局限性、疑点。请特别检查：
   - ground truth 的定义与潜在选择偏倚；
   - “预测”与“状态检测”是否被混淆，是否存在数据泄漏；
   - 相关、时间先后与因果/中介的区别；
   - 机理结论与模型推断的区别；
   - 临床部署约束（设备、算力、伪迹、安全性）。

凡是你没有从原文确认的内容，请标注【未核实】。

最后，请附上以下 YAML 元数据块（字段不知道就留空，不要编造）：

```yaml
paper:
  title:
  doi:
  url:
  code_url:
  year:
  venue:
  first_author:
  corresponding_authors: []
  team:
  paper_type:        # 原始研究 / 综述 / 数据资源 / 计算模型 / 方法与工具 / 临床试验 / 技术报告
  species: []
  diseases: []
  modalities: []     # 如 STN-LFP、ECoG、EEG、MEG、PSG、MRI、FDG-PET、仿真
  methods: []
  datasets: []
  devices: []
  sample_size:
  keywords: []
  one_liner:         # 一句话核心结论
  principles: []     # 本文体现的方法学原则，如 "temporal precedence ≠ causality"
  verification:      # 全文已读 / 部分章节 / 仅摘要 / 无法访问
```"""
