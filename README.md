# 多学科判卷接口自动化评测工具

该项目用于批量提交图片判卷任务、轮询接口结果、关联人工标注，并生成题干/答案相似度与分维度正确率报告。公开仓库不包含公司接口、访问令牌、原始图片、签名 URL 或业务 Excel。

## 处理流程

1. `01_image_folder_url.py`：可选，将图片上传到兼容 OSS 的对象存储并生成 URL 表。
2. `02_get_taskid.py`：批量调用任务提交接口，保存任务 ID，并支持断点续跑。
3. `03_folder_answer_fetch.py`：并发轮询任务状态，提取判卷结果。
4. `04_merge_excel.py`：按照年级、资料类型、名称和页码关联人工标注。
5. `05_answer_compare.py`：校验判题结果，并计算 Jaccard、余弦和编辑距离相似度。
6. `06_calculate_accuracy.py`：生成总体及分维度正确率统计。

## 安装

建议使用 Python 3.10 或更高版本。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置

复制环境变量示例并填写自己的测试服务配置：

```bash
cp .env.example .env
set -a
source .env
set +a
```

脚本不会自动加载 `.env`。也可以在终端或 CI 的 Secrets 中直接设置这些变量：

- `JUDGE_URL`：任务提交接口。
- `RESULT_BASE_URL`：结果接口基地址，末尾建议保留 `/`。
- `BEARER_TOKEN`：访问令牌。
- `OSS_ACCESS_KEY_ID`、`OSS_ACCESS_KEY_SECRET`、`OSS_ENDPOINT`、`OSS_BUCKET_NAME`：图片上传步骤使用的对象存储配置。

不要把真实令牌、签名 URL 或业务数据写入源码。

## 本地数据目录

四个学科目录均已写入 `.gitignore`，只在本地创建：

```text
CH/
├── CH_base.xlsx
└── answer_CH.xlsx
CN/
├── CN_base.xlsx
└── answer_CN.xlsx
EN/
├── EN_base.xlsx
└── answer_EN.xlsx
PH/
├── PH_base.xlsx
└── answer_PH.xlsx
```

`*_base.xlsx` 至少需要 `图片名称`、`图片URL` 列。人工标注表所需字段可参考 `04_merge_excel.py` 中的 `required_answer_cols`。

## 运行

处理全部四个学科：

```bash
bash run_multisubject.sh
```

只处理指定学科：

```bash
bash run_multisubject.sh CN EN
```

也可以逐步运行；使用 `-h` 查看每个 Python 脚本的参数说明。

## 数据安全

- `CH/`、`CN/`、`EN/`、`PH/`、`.env`、Excel、图片和运行结果默认不会被 Git 跟踪。
- 提交前建议执行 `git status`，并用密钥扫描工具检查暂存内容。
- 如果凭据曾进入 Git 历史，仅修改当前文件仍不安全；应轮换凭据，并使用没有旧历史的新仓库发布。
