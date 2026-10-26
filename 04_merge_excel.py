import pandas as pd
from pathlib import Path
import logging
import re
import sys
# 新增：配置日志格式（时间+级别+内容），确保能打印关键信息
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)



def clean_text(text):
    """清洗文本：去空格、全角转半角、去特殊字符"""
    if pd.isna(text):
        return ""
    # 转字符串并去首尾空格
    text = str(text).strip()
    # 全角括号转半角
    text = text.replace("（", "(").replace("）", ")")
    # 去所有空格（包括中间）
    text = text.replace(" ", "").replace("\u3000", "")
    # 去特殊符号（保留字母、数字、中文、括号）
    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9()]", "", text)
    return text

def extract_info_from_image_path(image_name):
    """
    从图片名称split(/)后提取信息
    返回：类型（练习册/试卷）、第4字段（试卷场景用）、图片页数（split后第5字段处理）
    图片名称类型：“化学/k10/练习册/-/page01_q01.png” or “语文/K4/试卷/K4期末达标测评卷(一)/page01_q01.png”
    """
    info = {"type": None, "field4": None, "image_page": None}
    # 按/分割，处理可能的分割后字段数不足5的情况
    parts = str(image_name).split("/")
    #field4==试卷名称部分
    # 1. 提取类型（split后第3个字段，索引为2）
    if len(parts) >= 3:
        third_field = parts[2].strip()
        if third_field in ["练习册", "作业本"]:
            info["type"] = "exercise_book"  # 练习册/作业本类型
            info["field4"]=third_field
        elif third_field == "试卷":
            info["type"] = "exam_paper"    # 试卷类型
            # 提取第4个字段（索引为3），用于试卷场景匹配B列
            if len(parts) >= 4:
                info["field4"] = parts[3].strip()

    # 2. 提取图片页数（split后第5个字段，索引为4，取page后的数字）
    if len(parts) >= 5:
        fifth_field = parts[4].strip()
        # 从类似"page02_q03.png"中提取page后的数字（如02）
        info["image_page"] = fifth_field.split(".")[0]  # 得到page02_q03

    return info

def match_and_merge_excels(answer_path, taskid_path, output_path):
    """
    按新规则匹配两个Excel并合并E-K列
    :param answer_path: 已填充的答案表路径（CN_1st_answer_filled.xlsx）
    :param taskid_path: 任务结果表路径（CN_1st_taskid_result.xlsx）
    :param output_path: 合并后输出文件路径
    """
    # 1. 读取Excel文件，指定引擎确保兼容性
    df_answer = pd.read_excel(answer_path, engine="openpyxl")
    df_taskid = pd.read_excel(taskid_path, engine="openpyxl")

    # 2. 检查必要列是否存在，缺失则报错
    required_answer_cols = ["年级", "B", "页数", "相对路径","grade","question_type_标注","question_标注","user_answer_标注","final_user_answer_标注", "is_correct", "是否包含材料", "是否包含图表", "书写杂乱度", "手写特征"]
    required_taskid_cols = ["图片名称", "年级"]

    # 验证答案表列
    missing_answer = [col for col in required_answer_cols if col not in df_answer.columns]
    if missing_answer:
        raise ValueError(f"答案表缺少必要列：{missing_answer}")
    # 验证任务表列
    missing_taskid = [col for col in required_taskid_cols if col not in df_taskid.columns]
    if missing_taskid:
        raise ValueError(f"任务表缺少必要列：{missing_taskid}")

    df_answer["B_clean"] = df_answer["B"].apply(clean_text)

    # 3. 为任务表添加匹配辅助列（提取图片路径信息）
    extract_result = df_taskid["图片名称"].apply(extract_info_from_image_path)
    df_taskid["匹配类型"] = [res["type"] for res in extract_result]
    df_taskid["试卷_第4字段"] = [res["field4"] for res in extract_result]
    df_taskid["图片_提取页数"] = [res["image_page"] for res in extract_result]

    # 4. 初始化E-K列（先设为空）grade	is_correct	是否包含材料	是否包含图表	书写杂乱度	手写特征	正确与否
    target_cols = [ "相对路径","grade","question_type_标注","question_标注","user_answer_标注","final_user_answer_标注", "is_correct", "是否包含材料", "是否包含图表", "书写杂乱度", "手写特征"]
    for col in target_cols:
        if col not in df_taskid.columns:
            df_taskid[col] = None

    # -------------------------- 5. 按类型执行匹配 --------------------------
    # 5.1 练习册/作业本类型匹配（匹配类型=exercise_book）
    exercise_mask = df_taskid["匹配类型"] == "exercise_book"
    if exercise_mask.any():
        for idx, task_row in df_taskid[exercise_mask].iterrows():
            # 匹配条件1：年级完全一致（答案表年级 = 任务表年级）
            cond1 = df_answer["年级"].str.lower() == str(task_row["年级"]).lower()

            # 匹配条件2：严格区分“练习册”和“作业本”
            # 获取任务表中的具体类型（存储在field4中，见extract_info_from_image_path）
            specific_type = task_row["试卷_第4字段"] # 这里复用了字段名，实际存储的是"练习册"或"作业本"
            if specific_type in ["练习册", "作业本"]:
                 cond2 = df_answer["B"].str.endswith(specific_type)
            else:
                 # 如果field4异常，则回退到旧逻辑（虽不应发生）
                 cond2 = df_answer["B"].str[-3:].isin(["练习册", "作业本"])

            # 匹配条件3：任务表“页数”列 与 图片提取的页数一致（需统一格式，如都是02而非2）
            task_page =  task_row["图片_提取页数"]
            extract_page = df_answer["页数"]
            cond3 = task_page == extract_page

            # 筛选所有满足条件的答案行，取第一行数据填充
            matched_answer = df_answer[cond1 & cond2 & cond3]
            if not matched_answer.empty:
                # 修正：取答案表中对应的6列值，填充到任务表
                fill_values = matched_answer.iloc[0][target_cols].values
                df_taskid.loc[idx, target_cols] = fill_values

    # 5.2 试卷类型匹配（匹配类型=exam_paper）
    exam_mask = df_taskid["匹配类型"] == "exam_paper"
    if exam_mask.any():
        for idx, task_row in df_taskid[exam_mask].iterrows():

            # -------------------------- 新增：日志打印 - 开始 --------------------------
            # 打印当前行的核心信息（定位是哪一行匹配失败）
            # logging.info(f"===== 试卷类型匹配 - 行索引：{idx} =====")
            # logging.info(f"图片名称：{task_row['图片名称']}")
            # logging.info(f"提取的field4（试卷名）：{task_row['试卷_第4字段']}")
            # logging.info(f"提取的页数：{task_row['图片_提取页数']}")
            # logging.info(f"任务表年级：{task_row['年级']}")
            # -------------------------- 新增：日志打印 - 结束 -------------------------

            # 步骤1：先过滤年级匹配的行（缩小匹配范围）
            grade_match_mask = df_answer["年级"].str.lower() == str(task_row["年级"]).lower()
            df_answer_grade_matched = df_answer[grade_match_mask].copy()

            # -------------------------- 新增：日志打印 - 开始 --------------------------
            # logging.info(f"年级匹配的答案行数量：{len(df_answer_grade_matched)}")
            # -------------------------- 新增：日志打印 - 结束 --------------------------

            # 步骤2：处理field4清洗（确保无特殊字符）
            field4 = clean_text(task_row["试卷_第4字段"])

            # 步骤3：重新定义匹配条件（仅在年级匹配的行内判断）
            # cond2：B_clean完全等于field4（因编码一致，用eq替代contains，避免正则干扰）
            cond2 = df_answer_grade_matched["B_clean"].eq(field4)
            # cond3：页数完全匹配
            task_page = task_row["图片_提取页数"]
            cond3 = df_answer_grade_matched["页数"].eq(task_page)

            # -------------------------- 新增：日志打印 - 开始 --------------------------
            # logging.info(f"清洗后的field4：{field4}")
            # logging.info(f"年级匹配行的B_clean：{df_answer_grade_matched['B_clean'].values}")
            # logging.info(f"年级匹配行的页数：{df_answer_grade_matched['页数'].values}")
            # logging.info(f"cond2（B_clean等于field4）：{cond2.values}")
            # logging.info(f"cond3（页数匹配）：{cond3.values}")
            # 打印总条件（cond2 & cond3）的结果
            total_cond = cond2 & cond3
            # logging.info(f"总匹配条件（cond2&cond3）：{total_cond.values}")
            # logging.info(f"满足总条件的行数：{total_cond.sum()}")
            # -------------------------- 新增：日志打印 - 结束 --------------------------

            # 筛选匹配的答案行，取第一行填充
            matched_answer = df_answer_grade_matched[total_cond]

            # -------------------------- 新增：日志打印 - 开始 --------------------------
            # logging.info(f"匹配到的答案行数量：{len(matched_answer)}")
            if not matched_answer.empty:
                 pass
                 # logging.info(f"匹配成功！填充数据：{matched_answer.iloc[0][['年级','B','页数']].to_dict()}")
            else:
                 pass
                 # logging.warning(f"匹配失败！未找到满足条件的答案行")
            # logging.info("="*50 + "\n")  # 分隔符，方便查看
            # -------------------------- 新增：日志打印 - 结束 --------------------------

            if not matched_answer.empty:
                fill_values = matched_answer.iloc[0][target_cols].values
                df_taskid.loc[idx, target_cols] = fill_values

    # 6. 清理辅助列，保存结果
    df_taskid_clean = df_taskid.drop(columns=["匹配类型", "试卷_第4字段", "图片_提取页数"], errors="ignore")
    df_taskid_clean.to_excel(output_path, index=False, engine="openpyxl")

    # 打印匹配统计（方便验证效果）
    matched_count = df_taskid_clean[["grade", "手写特征"]].notna().all(axis=1).sum()
    total_count = len(df_taskid_clean)
    print(f"匹配完成！输出文件：{output_path}")
    print(f"总数据行数：{total_count} | 成功匹配行数：{matched_count} | 未匹配行数：{total_count - matched_count}")

# ------------------- 主程序：指定路径并执行 -------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-gp", "--gt_path", type=str, required=True, help="Ground Truth / Answer Excel path")
    parser.add_argument("-vp", "--vis_path", type=str, required=True, help="Task Result Excel path (from step 03)")
    parser.add_argument("-op", "--output_path", type=str, required=True, help="Output Excel path")
    parser.add_argument("-sn", "--sheet_name", type=str, default="Sheet1", help="Sheet name (ignored in current logic)")

    args = parser.parse_args()

    ANSWER_FILE = Path(args.gt_path)
    TASKID_FILE = Path(args.vis_path)
    OUTPUT_FILE = Path(args.output_path)

    # 检查输入文件是否存在
    if not ANSWER_FILE.exists():
        print(f"答案文件不存在：{ANSWER_FILE}")
        sys.exit(1)
    if not TASKID_FILE.exists():
        print(f"任务文件不存在：{TASKID_FILE}")
        sys.exit(1)

    # 执行匹配合并（捕获异常并提示）
    try:
        match_and_merge_excels(ANSWER_FILE, TASKID_FILE, OUTPUT_FILE)
        print("✅ 合并任务已完成！")
    except Exception as e:
        print(f"❌ 执行失败：{str(e)}")
        sys.exit(1)