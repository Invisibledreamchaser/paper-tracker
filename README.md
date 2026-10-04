# 📡 paper-tracker 论文雷达

一个 ZCode skill：输入任意研究方向 + 时间段，自动检索 **PubMed（正式期刊）** 与 **arXiv（预印本）** 的新发表论文，按期刊/分类分组，生成中文报告。

> 示例：「医学图像维度增强 最近一周有哪些新论文？」→ 得到按 IEEE TIP、Radiology、arXiv cs.CV 等分组的论文清单，每篇附一句话中文总结和链接。

## 功能

- 🏥 **期刊分组**：PubMed 侧按期刊全称分组（TMI、Medical Image Analysis、Radiology、Ultrasound Med Biol 等均在收录范围），期刊按文章数排序
- 🌐 **全出版社覆盖**：通过 OpenAlex 聚合 IEEE、Elsevier/ScienceDirect、Springer、Wiley、MDPI、ACM 等 2.5 亿+ 文献库，补齐 PubMed 收录之外的期刊；自动与 PubMed 按 DOI/标题去重，只保留真正的期刊来源（剔除 Zenodo/DOAJ 等仓库条目）
- 📦 **预印本分组**：arXiv 侧按主分类（cs.CV / eess.IV / physics.med-im 等）分组
- ⏱️ **时间段自选**：今天 / 最近一周（默认）/ 最近一个月 / 任意日期区间
- 🇨🇳 **中文检索**：直接输入中文方向，自动扩展为英文布尔检索式
- 📝 **一句话总结**：每篇论文附 20~40 字中文摘要总结（基于真实 abstract，不编造）
- ⚠️ **同文去重提示**：arXiv 预印本与期刊版同名时自动标注
- 📄 **一键取全文**：按 DOI 自动解析开放获取 PDF（OpenAlex OA 链接 → 出版商直链 → Crossref 直链，含 Nature 系兜底模式），付费墙论文自动回退为链接
- 🔑 **零配置**：使用 arXiv / NCBI / OpenAlex 官方公开 API，无需任何 API Key，仅依赖 Python 标准库

## 安装

把本仓库克隆到 ZCode 的用户级 skill 目录：

```bash
git clone https://github.com/Invisibledreamchaser/paper-tracker.git "$HOME/.agents/skills/paper-tracker"
```

重启 ZCode 会话即可。之后直接用自然语言提问即可触发，例如：

```
diffusion model 用于 MRI 重建，最近一个月有什么新文章
```

## 工作原理

1. 将研究方向翻译/扩展为英文布尔检索式（单个 OR 短语组，同义词放宽度）
2. 调用脚本同时检索三个数据源：
   - **arXiv API**：分类过滤 + `submittedDate` 时间窗 + 关键词，按提交日期排序
   - **PubMed E-utilities**：esearch（日期窗口）→ esummary（期刊/DOI）→ efetch（摘要）
   - **OpenAlex**：全出版社期刊文章，`title_and_abstract.search`（短语自动改为 `|` OR 语义）+ 日期窗口，按相关度排序，只保留期刊来源并与 PubMed 去重
3. 脚本输出按期刊/分类分组的 Markdown 草稿
4. 模型筛选域外噪音、合并两路期刊结果、为每篇撰写中文一句话总结，生成最终报告文件

## 文件结构

```
paper-tracker/
├── SKILL.md              # skill 主流程（ZCode 读取的入口）
├── README.md
├── LICENSE
└── scripts/
    ├── fetch_papers.py   # arXiv + PubMed + OpenAlex 检索脚本（纯标准库）
    └── fetch_pdf.py      # 按 DOI / arXiv id 下载开放获取 PDF
```

### 获取某篇论文的全文 PDF

```bash
python scripts/fetch_pdf.py --doi 10.1038/s41598-026-73833-9 --out DRR-pipeline.pdf
python scripts/fetch_pdf.py --arxiv 2411.06308 --out ood-sparse-view-ct.pdf
```

OA 论文直接落盘；付费墙论文会打印 DOI 链接与文章页面。

## 环境要求

- Python 3.8+（仅标准库，无需 pip install）
- 网络可访问 `export.arxiv.org`、`eutils.ncbi.nlm.nih.gov` 与 `api.openalex.org`

## 已知事项

- PubMed 对最近 1~3 天发表的文章收录有延迟，查"今天"的期刊文章可能偏少，预印本部分看 arXiv
- 检索式设计为"宽检索 + 智能筛选"：宁可多召回，由模型在报告环节剔除域外命中（如显微 super-resolution、通用 3D 重建）
- Windows 上若 Python 缺少 CA 证书包，脚本会自动回退（两个 API 均为公开只读接口）

## License

见 [LICENSE](LICENSE)。
