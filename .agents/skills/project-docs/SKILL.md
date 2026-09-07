---
name: project-docs
description: Use when writing, editing, or organizing BluraySubtitle README files, code standards, wiki pages, development documentation, or refactoring history, or deciding whether code changes require documentation updates. 编写、修改或整理 BluraySubtitle 的 README、代码规范、wiki、开发文档和重构历史，以及判断代码变更是否需要更新文档时使用。
---

# Project Documentation Maintenance / 项目文档维护

[English](#english) | [简体中文](#简体中文)

## English

Identify the readers and each document's purpose before deciding whether and where actual behavior requires documentation changes. Follow the [Code Modification Standards](../../../docs/development/code-standards.md) and their [Simplified Chinese version](../../../docs/development/code-standards.zh-Hans.md), keeping existing English and Chinese documents synchronized.

### Readers and scope

| Document | Readers | Purpose and scope |
| --- | --- | --- |
| README | Software users, including the software author and everyone else using it | Include only information useful for using and operating the software. Exclude implementation details; link to other documents for explanations of underlying principles. |
| Code standards | AI agents and PR contributors, primarily agents | Accurately record established development rules and necessary product constraints. |
| Wiki | Users interested in the software's principles and related knowledge, and developers; individual pages have different emphases | Accurately explain concepts, principles, or implementation according to each page's topic, with a clear structure. |
| Refactoring history | Developers | Record actual changes that provide useful context, for reference only. Do not treat history as a standard or routinely restructure existing entries. |

### Deciding whether to update documentation

- Base changes on actual functionality, operation, and documentation gaps. Do not copy task instructions into documents or turn instructions to leave something unchanged into a list of unchanged items.
- Add no text when a fix merely restores behavior already covered by the documentation. Enhancements confined to implementation details also warrant no added text.
- Except in refactoring history, do not document every item in a change list. Describe only the current state readers need to understand; omit retired behavior.
- Be especially restrained in README files and the code standards' "Confirmed Product Constraints" section: do not add descriptions of previously undocumented detail improvements that have little effect on user operation.

### Organization and wording

- Choose the appropriate file and location before adding content. Integrate wiki additions into the relevant section when one exists; otherwise add a section for the topic rather than placing content under an unrelated heading.
- Use concise, accurate language and remove redundant paragraphs. Keep one complete explanation of each topic and link to it elsewhere, targeting specific sections when needed.
- Do not use development-process or personal-environment wording such as "author," "this change," or "local" in user-facing documents, or include paths specific to a personal machine. Use placeholder paths, environment variables, or project-relative paths in operational examples.
- Do not record unchanged items in any document. When removing outdated or unnecessary explanations, do not add text explaining their removal.
- README files must omit identification, probing, caching, cleanup, or build details that provide no value for using the software.
- Product constraints in the code standards should cover only necessary exceptions and potentially ambiguous product semantics, without accumulating algorithm steps, interface details, or change records.
- New refactoring history entries should record only actual changes with development reference value and necessary validation, excluding facts relevant only to a single run. Do not rewrite existing history during routine documentation cleanup.

### Final checks

Check that content fits its intended readers and section, and is neither redundant, outdated, nor a restatement of task instructions. Confirm that English and Chinese meanings match and that links and section anchors work. Check encoding, line endings, and diffs according to the code standards; do not add test files for wording or document structure.

## 简体中文

先确定读者和文档职责，再根据实际行为决定是否修改、修改哪些文件。遵守[代码修改规范](../../../docs/development/code-standards.zh-Hans.md)及其[英文版](../../../docs/development/code-standards.md)，已有中英文文档须同步更新。

### 读者与范围

| 文档 | 读者 | 作用与范围 |
| --- | --- | --- |
| README | 软件使用者，包括软件作者及其他所有使用软件的人 | 只包含对使用和操作有价值的信息。不得包含实现细节；需要解释原理时链接到其他文档。 |
| 代码规范 | 各种 AI Agent 和提交 PR 的贡献者，主要是 Agent | 如实记录已确立的开发规则与必要的产品约束。 |
| wiki | 希望了解软件原理及相关知识的用户，以及开发者；各页面有所侧重 | 根据页面主题如实解释概念、原理或实现，保持内容结构清楚。 |
| 重构历史 | 开发者 | 记录有参考价值的实际变更，仅供参考，不作为规范；一般不重构已有历史。 |

### 是否需要修改

- 以实际功能、操作和文档缺口为依据，禁止把任务指令直接抄入文档，或将“不要修改”的要求写成未改动事项。
- 修复后仅恢复文档已经描述的行为、没有超出其范围时，不应增加任何文字。新增代码仅增强实现细节时，也不为此增加文字。
- 除重构历史外，不按修改清单事无巨细地记录变更；只描述读者需要了解的当前状态。已停用的行为不再提及。
- README 和代码规范的“已确认的产品约束”尤其需要克制：对用户操作影响不大、此前也没有描述的细节改进，不专门新增说明。

### 如何组织与表达

- 新增内容前先选择合适的文件和位置。wiki 已有相关内容时并入对应段落；没有合适位置时新增主题段落，不得塞入无关段落。
- 使用简洁、准确的语言，删除冗余段落。同一内容保留一处完整说明，其他位置用链接关联；需要定位时链接到具体段落。
- 面向用户的文档禁止使用“作者”“本次修改”“本地”等以开发过程或个人环境为中心的表述，也不得出现具体的个人机器路径。操作示例使用占位路径、环境变量或项目相对路径。
- 所有文档都不得记录未修改事项。删除过时或多余说明时，不再补充解释删除原因。
- README 不记录对使用无价值的识别、探测、缓存、清理或构建细节。
- 代码规范的产品约束只保留必要例外和容易产生歧义的产品语义，避免堆积算法步骤、界面细节或修改记录。
- 新增重构历史只记录有开发参考价值的实际变化和必要验证，不记录只对一次运行有意义的事实。已有历史不因日常文档整理而改写。

### 完成检查

检查内容是否属于目标读者和所在段落，是否重复、过时或只复述指令；确认中英文含义一致，链接及段落锚点有效。按代码规范检查文本编码、换行和差异，不为措辞或文档结构新增测试文件。
