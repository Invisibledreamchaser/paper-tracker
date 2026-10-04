---
name: paper-tracker
description: 按研究方向检索最新发表论文并按期刊分组，生成中文文献雷达报告（日报/周报/月报）。当用户想知道某个研究领域最近（今天/最近一周/最近一个月）新发表了什么文章、期刊有什么更新、想追踪某方向的最新文献或论文日报时使用——即使用户只说"帮我看看 XX 方向最近有什么新论文"也应触发。使用 PubMed 与 arXiv 官方 API，无需任何密钥。
---

# Paper Tracker — 研究方向论文雷达

根据用户给的研究方向与时间范围，检索新论文并生成中文报告。三个数据源（均无需 API 密钥）：

- **PubMed**：生物医学正式期刊（TMI、Med Image Anal、Radiology 等），含摘要，按期刊分组
- **OpenAlex**：全出版社期刊覆盖（IEEE、Elsevier/ScienceDirect、Springer、Wiley、MDPI、ACM 等），按相关度返回，用于补齐 PubMed 收录之外的期刊
- **arXiv**：预印本，按分类分组

脚本会自动把 OpenAlex 结果与 PubMed 去重（按 DOI/标题），并在 arXiv 条目上标注疑似已有期刊版本的文章。

## 第 1 步：解析输入

- **研究方向**：可能是中文（如"医学图像维度增强"），你需要翻译并扩展成英文检索词。
- **时间段**：`今天`→`--days 1`，`最近一周/本周`→7，`最近一个月`→30；用户给出明确日期时用 `--start/--end`。用户未提时间时默认 7 天，并在报告开头注明所用窗口。
- 用系统当前日期计算窗口（可先 `date +%F` 确认今天日期）。
- 用一句话向用户复述你将使用的英文检索式和时间窗口，然后直接执行，不必等确认。

## 第 2 步：构造英文检索式（决定成败）

把研究方向扩展成英文布尔检索式，交给脚本的 `--query`。**核心原则：只用一个 OR 短语组（2~8 个核心概念短语），不要用多组短语再 AND 嵌套**——arXiv API 对多组引号短语做 AND 时会因精确短语匹配而把命中数压到接近 0（实测同一窗口下：单组 42 篇 → 双组 AND 后 1 篇）。

- 短语用英文双引号包裹，同义词/上下位词用 `OR` 连接，布尔运算符必须全大写。示例：

  ```
  医学图像维度增强 →
  "sparse-view" OR "sparse view" OR "2D to 3D" OR "3D reconstruction" OR "dimension enhancement" OR "super-resolution"
  ```

- **arXiv 侧的领域收窄交给分类**（`--arxiv-cats`），不要往检索式里堆 AND：
  - 医学影像/计算机视觉：`cs.CV,eess.IV,physics.med-im`；深度学习：`cs.CV,cs.LG,cs.AI`；NLP：`cs.CL`；机器人：`cs.RO`；不确定就不传。
- PubMed 语料本身就是生物医学的，单组短语通常够用；OpenAlex 覆盖全出版社，宽检索会带来更多域外命中（如遥感、化学期刊），由你在第 4 步筛掉。
- 各来源的语法差异由脚本自动适配（arXiv 要求大写 AND/OR；OpenAlex 会被转成 OR 语义并按相关度排序），你只管把短语组写好。
- 用户点名某些期刊时（如"只要 TMI 和 Med Image Anal"），有两种方式：
  - PubMed 侧：在检索式后加 `AND ("IEEE Trans Med Imaging"[Journal] OR "Med Image Anal"[Journal])`
  - OpenAlex 侧：传 `--openalex-journals "IEEE Transactions on Medical Imaging,Medical Image Analysis"`（逗号分隔期刊名，任一匹配即召回）
- 跑完后看脚本打印的命中数微调：**0 篇** → 增加同义词、去掉 AND 限定或加大 `--days`；**超过 ~200 篇** → 在检索式后追加一个 AND 概念词（单词或单个短语，如 `AND MRI`）再跑。

## 第 3 步：运行检索脚本

```bash
python <skill目录>/scripts/fetch_papers.py \
  --query '<英文检索式>' \
  --days 7 \
  --arxiv-cats cs.CV,eess.IV,physics.med-im \
  --out paper_draft.md
```

- `<skill目录>` 是本 skill 的 base directory（加载本 skill 时已给出）。
- 脚本会在 stdout 打印各来源/各期刊命中统计，并把分组草稿写入 `--out` 文件（含标题、作者、日期、期刊、链接、摘要）。
- **某来源 0 结果时**：放宽检索式（去掉部分 AND 限定、增加同义词）或加大 `--days` 重跑一次。注意 PubMed 收录有 1~3 天延迟，最近两三天的期刊文章查不到属正常现象，在报告中说明即可，不要反复空跑。

## 第 4 步：生成最终报告

用 Read（必要时分段 offset/limit）读草稿文件，然后：

1. **先筛选**：把明显不属于用户领域的命中剔除（宽检索常见：植物学期刊的 "super-resolution microscopy"、化学期刊的 "2D to 3D"、纯自动驾驶的 "3D reconstruction" 等）。判断依据是摘要内容与用户方向的相关性，拿不准的保留。剔除数量在报告统计行注明"已筛除 N 篇边缘命中"。
2. 为留下的每篇论文写一句 20~40 字的中文总结（基于摘要：做了什么 + 核心亮点/结果），不要照抄摘要原句。
3. 把报告保存为 `paper-radar_<方向slug>_<结束日期>.md`（UTF-8），方向 slug 用短横线英文（如 `medical-image-dimension-enhancement`）。
4. 在聊天中展示报告内容。格式严格遵守（**PubMed 与 OpenAlex 的条目合并进同一个"期刊论文"板块**；同一期刊在两个来源名称略有差异时视为同一期刊，采用较简洁的规范名）：

```markdown
# 📡 论文雷达：医学图像维度增强
> 窗口 2026-09-27 ~ 2026-10-03 ｜ 期刊 14 篇（PubMed 12 · OpenAlex 新增 2）· arXiv 预印本 8 篇 ｜ 检索式：`...`

## 🏥 期刊论文（按期刊；来源 = PubMed + OpenAlex 全出版社）
### IEEE Transactions on Image Processing（2 篇）
1. **Learning-Based Sparse-View CT Reconstruction**
   - Zhang S, et al. ｜ 2026-09-30 ｜ [PubMed](https://pubmed.ncbi.nlm.nih.gov/12345678/)
   - 提出一种……在两个数据集上将伪影减少了 32%。
2. **Another Paper Found Only via OpenAlex**
   - Chen L, et al. ｜ 2026-09-28 ｜ [DOI](https://doi.org/10.1109/xxx)
   - 一句中文总结。
（其余期刊同理，期刊按文章数从多到少排）

## 📦 arXiv 预印本（按分类）
1. **Title of the Preprint** ⚠️（疑似已有期刊同名论文）
   - Chen L, et al. ｜ 提交 2026-10-01 ｜ [arXiv:2610.01234](https://arxiv.org/abs/2610.01234)
   - 一句中文总结。
```

规则：

- arXiv 文章没有期刊概念，按主分类分组并标注"预印本，未经同行评审"；脚本已对 arXiv 与期刊同名文章标注 ⚠️，保留两处即可。
- OpenAlex 部分的域外噪音通常比 PubMed 多（宽检索 + 全出版社），筛选要更狠，宁可少而准；OpenAlex 对最新文章的收录也可能比 PubMed 慢几天，报告里不用刻意区分来自哪个来源，统一按期刊呈现。
- 聊天中展示完整分组列表；若总篇数超过 ~30，聊天里每个期刊只列前 5 篇并注明"其余 N 篇见文件"，但**文件里必须完整收录全部条目**。
- 报告末尾附一行：统计数字 + 所用检索式 + 检索窗口，方便用户复现或调整。
- 用户想看某篇详情时，直接给出 PubMed/DOI/arXiv 链接并总结摘要，不要虚构实验数字——摘要里没有的信息不要编。

## 第 5 步：获取全文 PDF（用户要原文时）

对用户点名要全文/文件的论文，按 DOI 下载开放获取版本：

```bash
python <skill目录>/scripts/fetch_pdf.py --doi <DOI> --out <文件名>.pdf   # 期刊论文
python <skill目录>/scripts/fetch_pdf.py --arxiv <id> --out <文件名>.pdf  # arXiv 论文
```

- 脚本按"OpenAlex OA 链接 → 由 DOI 推导的出版商直链（Nature 系含 `_reference.pdf` 兜底，即正式全文）→ Crossref 出版商直链"的顺序尝试，并校验 `%PDF` 魔数防止存下 HTML。
- 下载成功 → 把 PDF 文件路径告诉用户；失败（通常是 IEEE/Elsevier/Springer 付费墙）→ 给出 DOI 链接和文章页面，说明受版权限制、建议通过机构订阅获取，不要反复重试。
- 主动附 PDF 的好时机：报告中 OA 期刊（Scientific Reports、BMC 系、Frontiers 系、arXiv 预印本）的文章基本都能直接下载；同一论文同时有 arXiv 版时脚本会自动选中可下载的那份。
