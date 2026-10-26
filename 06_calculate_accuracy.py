import pandas as pd
import numpy as np
import re
import argparse
import sys
from pathlib import Path

def normalize_question_type(q_type):
    """
    将题型映射到标准分类：
    单选/多选/单空填空/多空填空/判断/排序/配对/其他客观题/简答题/解答题/写作题/翻译题/其他主观题
    """
    if pd.isna(q_type):
        return ""

    q_str = str(q_type).strip()
    m_cn = re.search(r'（(.*?)）', q_str)
    m_en = re.search(r'\((.*?)\)', q_str)
    inner = None
    if m_cn:
        inner = m_cn.group(1)
    elif m_en:
        inner = m_en.group(1)
    if inner is not None:
        inner_clean = inner.replace(" ", "").replace("\t", "").replace("\n", "").lower()
        if "单空" in inner_clean or "single_blank" in inner_clean:
            return "单空填空"
        if "多空" in inner_clean or "multiple_blank" in inner_clean:
            return "多空填空"
    # 预处理：
    # 1. 移除括号及括号内的内容 (支持中文括号和英文括号)
    #    例如： "填空（多空）" -> "填空"
    q_str = re.sub(r'（.*?）', '', q_str)
    q_str = re.sub(r'\(.*?\)', '', q_str)

    # 2. 移除空白字符，统一小写
    clean_str = q_str.replace(" ", "").replace("\t", "").replace("\n", "").lower()

    # 映射规则 (关键词匹配，优先级从上到下)
    if "单选" in clean_str or "single_choice" in clean_str:
        return "单选"
    if "多选" in clean_str or "multiple_choice" in clean_str:
        return "多选"
    if "单空" in clean_str or "single_blank" in clean_str:
        return "单空填空"
    if "多空" in clean_str or "multiple_blank" in clean_str:
        return "多空填空"
    if "填空" in clean_str or "fill_in_the_blank" in clean_str:
        if "多" in clean_str:
            return "多空填空"
        return "单空填空"
    if "判断" in clean_str or "true_false" in clean_str or "judgment" in clean_str:
        return "判断"
    if "排序" in clean_str or "sorting" in clean_str or "ordering" in clean_str:
        return "排序"
    if "配对" in clean_str or "matching" in clean_str:
        return "配对"
    if "简答" in clean_str or "short_answer" in clean_str:
        return "简答题"
    if "解答" in clean_str or "calculation" in clean_str or "comprehensive" in clean_str:
        return "解答题"
    if "写作" in clean_str or "writing" in clean_str or "composition" in clean_str:
        return "写作题"
    if "翻译" in clean_str or "translation" in clean_str:
        return "翻译题"
    if "主观" in clean_str:
        return "其他主观题"
    if "客观" in clean_str:
        return "其他客观题"

    # 默认返回原值或归为"其他"
    return clean_str

def calculate_accuracy(df, group_col):
    """
    计算指定分组列的正确率
    df: 原始数据DataFrame
    group_col: 分组列名
    返回包含分组、总题数、正确题数、正确率的DataFrame
    """
    # 按分组列和正确与否列分组统计
    stats = df.groupby([group_col, '正确与否']).size().unstack(fill_value=0)
    # 确保Y列（正确）存在
    if 'Y' not in stats.columns:
        stats['Y'] = 0
    # 计算总题数和正确率
    stats['总题数'] = stats.sum(axis=1)
    stats['正确题数'] = stats['Y']
    stats['正确率'] = (stats['正确题数'] / stats['总题数']).round(4) * 100  # 保留4位小数，转为百分比
    # 重置索引，使分组列成为普通列
    result = stats[['总题数', '正确题数', '正确率']].reset_index()
    return result

def main():
    parser = argparse.ArgumentParser(description="Calculate accuracy from test results.")
    parser.add_argument("-ip", "--input_path", type=str, required=True, help="Input Excel file path")
    parser.add_argument("-op", "--output_path", type=str, required=True, help="Output Excel file path")
    parser.add_argument("-sn", "--subject_name", type=str, default='学科未知', help="subject name")
    args = parser.parse_args()

    input_file = args.input_path
    output_file = args.output_path
    subject_name = args.subject_name

    if not Path(input_file).exists():
        print(f"Error: Input file does not exist: {input_file}")
        sys.exit(1)

    # 读取原始Excel文件
    try:
        df = pd.read_excel(input_file, sheet_name='Sheet1', engine='openpyxl')
    except Exception as e:
        print(f"Error reading input file: {e}")
        # Try reading without sheet name if Sheet1 fails
        try:
            df = pd.read_excel(input_file, engine='openpyxl')
        except Exception as e2:
             print(f"Error reading input file (retry): {e2}")
             sys.exit(1)

    # 数据预处理：筛选有效数据（排除"无效"记录）
    if '正确与否' not in df.columns:
        print("Error: Column '正确与否' not found in input file.")
        sys.exit(1)

    df_valid = df[df['正确与否'] != '无效'].copy()

    # 定义需要统计的列
    # 注意：确保这些列在输入文件中存在，不存在则跳过
    possible_columns = ['grade', '是否包含材料', '是否包含图表', '书写杂乱度', '手写特征', 'question_type']
    target_columns = [col for col in possible_columns if col in df.columns]

    if 'question_type_标注' in df.columns and 'question_type' not in target_columns:
         # Special handling: if we have question_type_标注 but want to group by normalized type,
         # logic below handles it via question_type_normalized derived from question_type_标注.
         # But original code iterates over 'question_type'.
         # Let's keep 'question_type' in target_columns if we can derive it.
         if 'question_type' not in target_columns:
             target_columns.append('question_type')

    # 存储所有统计结果
    all_results = []

    # 遍历每个目标列，计算正确率
    for col in target_columns:
        # 针对 question_type 列进行特殊归一化处理
        if col == 'question_type':
            if 'question_type_标注' in df_valid.columns:
                df_valid['question_type_normalized'] = df_valid['question_type_标注'].apply(normalize_question_type)
                result = calculate_accuracy(df_valid, 'question_type_normalized')
            elif 'question_type' in df_valid.columns:
                 # Fallback if question_type_标注 is missing
                 df_valid['question_type_normalized'] = df_valid['question_type'].apply(normalize_question_type)
                 result = calculate_accuracy(df_valid, 'question_type_normalized')
            else:
                continue
        else:
            result = calculate_accuracy(df_valid, col)

        # 注意：如果归一化了，分组列名会变成 'question_type_normalized'，需要统一处理
        group_col_name = 'question_type_normalized' if col == 'question_type' else col

        # 确保result里有这个列（calculate_accuracy返回的result里已经reset_index，列名就是group_col）
        # 先只取需要的列，此时还没有'统计类型'
        result = result[[group_col_name, '总题数', '正确题数', '正确率']]

        # 重命名分组列为"分组值"
        result.rename(columns={group_col_name: '分组值'}, inplace=True)

        # 添加统计类型列，区分不同情况
        result['统计类型'] = col

        # 重新排列最终列顺序
        result = result[['统计类型', '分组值', '总题数', '正确题数', '正确率']]

        all_results.append(result)

    # 合并所有统计结果
    if all_results:
        final_result = pd.concat(all_results, ignore_index=True)
    else:
        final_result = pd.DataFrame(columns=['统计类型', '分组值', '总题数', '正确题数', '正确率'])

    # ========== 核心修改：计算总正确率并添加到表格最后一行 ==========
    # 计算总正确率
    if len(df_valid) > 0:
        total_correct = len(df_valid[df_valid['正确与否'] == 'Y'])  # 有效数据中正确题数
        total_count = len(df_valid)  # 有效数据总数
        total_accuracy = round((total_correct / total_count) * 100, 4)   # 总正确率（百分比）
    else:
        total_correct = 0
        total_count = 0
        total_accuracy = 0.0

    # 构造总正确率行（列名与final_result保持一致）
    total_row = pd.DataFrame({
        '统计类型': ['学科'],
        '分组值': [subject_name],
        '总题数': [total_count],
        '正确题数': [total_correct],
        '正确率': [total_accuracy]
    })

    # 将总正确率行追加到最终结果末尾
    final_result = pd.concat([final_result, total_row], ignore_index=True)

    # ========== 新增：细节维度统计 ==========
    detail_dims = ['是否包含图表', '是否包含材料', '书写杂乱度', '手写特征']
    sim_cols = ['题干文本相似度', '手写答案相似度', '手写最终答案相似度', '解题最终答案相似度']
    check_cols = ['判题结果个数对', '题型检查']

    detail_results = []

    # 预处理：将相似度列转换为数值型，非数值（如"-"）强制转换为NaN
    for col in sim_cols:
        if col in df_valid.columns:
            df_valid[col] = pd.to_numeric(df_valid[col], errors='coerce')

    # 1. 维度相似度统计
    for dim in detail_dims:
        # 检查维度列是否存在
        if dim not in df_valid.columns:
            # print(f"跳过维度 {dim}: 列不存在")
            continue

        # 按维度分组
        grouped = df_valid.groupby(dim)

        # 计算相似度均值 (自动忽略NaN)
        # 检查sim_cols是否都在df中
        valid_sim_cols = [c for c in sim_cols if c in df_valid.columns]
        if valid_sim_cols:
            sim_stats = grouped[valid_sim_cols].mean().round(4)
        else:
            sim_stats = pd.DataFrame(index=grouped.groups.keys())

        # 合并统计结果
        combined = sim_stats.reset_index()
        combined['统计维度'] = dim
        combined.rename(columns={dim: '分组值'}, inplace=True)

        # 调整列顺序
        # Ensure '分组值' is in columns before selecting
        cols = ['统计维度', '分组值'] + valid_sim_cols
        # Only select columns that exist
        cols = [c for c in cols if c in combined.columns]
        combined = combined[cols]

        detail_results.append(combined)

    if detail_results:
        final_detail_result = pd.concat(detail_results, ignore_index=True)
    else:
        final_detail_result = pd.DataFrame()

    # 2. 全量判题/题型检查统计 (不分维度，只统计全局)
    check_results = []
    valid_check_cols = [c for c in check_cols if c in df_valid.columns]

    for col in valid_check_cols:
        total = len(df_valid)
        # Ensure column values are strings for comparison, handle NaN
        correct = (df_valid[col].astype(str) == 'Y').sum()
        accuracy = round((correct / total) * 100, 2) if total > 0 else 0.0

        check_results.append({
            '统计项': col,
            '总题数': total,
            '正确数': correct,
            '正确率': accuracy
        })

    final_check_result = pd.DataFrame(check_results)

    # ========== 新增：实际处理耗时统计 ==========
    time_stat_df = pd.DataFrame()
    if '实际处理耗时' in df_valid.columns:
        # 预处理：解析 "MM:SS.mmm" 格式
        # 策略：如果是 "beyond1h" 或无法解析，转为 NaT
        # 如果符合 \d{2}:\d{2}(\.\d+)? 格式，前面补 "00:" 以便 pd.to_timedelta 正确识别为分钟
        def parse_duration(x):
            s = str(x).strip()
            if s == "beyond1h" or pd.isna(x):
                return pd.NaT
            # 简单判断是否为 MM:SS 格式（如 05:30.123）
            if re.match(r'^\d{2}:\d{2}(\.\d+)?$', s):
                return pd.to_timedelta("00:" + s)
            # 兜底尝试标准解析
            return pd.to_timedelta(s, errors='coerce')

        times = df_valid['实际处理耗时'].apply(parse_duration)
        avg_time = times.mean()
        if pd.notnull(avg_time):
             # 格式化平均耗时为 MM:SS.mmm
             total_seconds = avg_time.total_seconds()
             minutes = int(total_seconds // 60)
             seconds = int(total_seconds % 60)
             millis = int(avg_time.microseconds / 1000)
             avg_time_str = f"{minutes:02}:{seconds:02}.{millis:03}"

             time_stat_df = pd.DataFrame({
                 '统计项': ['实际处理耗时平均值'],
                 '平均耗时(MM:SS.mmm)': [avg_time_str]
             })

    # ========== 写入Excel文件 ==========

    try:
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            final_result.to_excel(writer, sheet_name='正确率统计', index=False)

            # 准备细节维度统计的各个板块
            sections = []
            if not final_detail_result.empty:
                sections.append((None, final_detail_result))

            if not final_check_result.empty:
                # 如果前面有板块，则添加标题
                title = '全量检查项统计' if sections else None
                sections.append((title, final_check_result))

            if not time_stat_df.empty:
                title = '耗时统计' if sections else None
                sections.append((title, time_stat_df))

            current_row = 0
            for idx, (title, df) in enumerate(sections):
                # 写入标题（如果存在）
                if title:
                    # 此时Sheet肯定已存在（因为title存在意味着不是第一个板块）
                    worksheet = writer.sheets['细节维度统计']
                    # openpyxl row is 1-based
                    worksheet.cell(row=current_row + 1, column=1, value=title)
                    current_row += 1 # 下移一行给Table

                # 写入数据
                df.to_excel(writer, sheet_name='细节维度统计', index=False, startrow=current_row)
                current_row += len(df) + 1 + 2 # +1 for header, +2 for spacing

        # 终端输出信息
        print(f"统计完成！结果已保存至 {output_file}")
        print("\n统计概况：")
        print(f"有效数据总题数：{total_count}")
        print(f"统计维度：{', '.join(target_columns)}")
        print(f"总正确率：{total_accuracy}%")

    except Exception as e:
        print(f"Error writing output file: {e}")
        sys.exit(1)

if __name__ == "__main__":

    main()
