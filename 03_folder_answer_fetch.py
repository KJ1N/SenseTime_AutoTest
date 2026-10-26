
import sys
import os
import json
import requests
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from pathlib import Path
import argparse

# ======================== 默认配置 ========================
DEFAULT_SLEEP_TIME = 0.5
DEFAULT_TIMEOUT = 1440  # 1 day in minutes
DEFAULT_INTERVAL = 60   # 1 minute in seconds
# ========================================================

class TaskResultFetcher:
    def __init__(self, api_url, bearer_token, sleep_time=0.5, txt_save_path=None):
        self.API_URL = api_url
        self.bearer_token = f"Bearer {bearer_token}" if bearer_token else ""
        self.sleep_time = sleep_time
        self.txt_save_path = txt_save_path
        self.lock = threading.Lock()

        # Initialize/clear the output file if it's specified
        if self.txt_save_path:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(self.txt_save_path)), exist_ok=True)
            # Create/Empty the file
            with open(self.txt_save_path, "w", encoding="utf-8") as f:
                f.write("")

    def check_task_status(self, task_id, img_name):
        """
        检查单个task ID的状态
        返回: (status, result_data)
        status: "completed", "failed", "processing", "unknown"
        result_data: 提取的数据或None
        """
        if not task_id:
            return "failed", None

        headers = {
            "Authorization": self.bearer_token,
            "Content-Type": "application/json"
        }

        try:
            # 发送GET请求
            response = requests.get(
                f"{self.API_URL}result?task_id={task_id}",
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            response_json = response.json()

            data = response_json.get("data", {})
            state = data.get("state")

            if state == "completed":
                # 保存响应 (Thread-safe write to single file)
                if self.txt_save_path:
                    with self.lock:
                        with open(self.txt_save_path, "a", encoding="utf-8") as f:
                            f.write(f"========== {img_name} - {task_id} ==========\n")
                            json.dump(response_json, f, ensure_ascii=False, indent=4)
                            f.write("\n\n")

                # 提取字段
                results = data.get("result", [])
                is_right_parts_list = []
                # question_category_list = []
                question_type_list = []
                question_list = []
                user_answer_list = []
                user_final_answer_list = []
                final_right_answer_list = []

                for res in results:
                    irp = res.get("is_right_parts")
                    if irp is not None:
                        is_right_parts_list.extend(irp)
                    # qt = res.get("question_category")
                    # if qt:
                    #     question_category_list.append(qt)
                    qc = res.get("question_type")
                    if qc:
                        question_type_list.append(qc)

                    # 提取新字段
                    q = res.get("question")
                    if q:
                        question_list.append(q)

                    ua = res.get("user_answer")
                    if isinstance(ua, list):
                        user_answer_list.extend(ua)
                    elif isinstance(ua, str):
                        user_answer_list.append(ua)

                    ufa = res.get("user_final_answer")
                    if ufa:
                        user_final_answer_list.append(ufa)

                    fra = res.get("final_right_answer")
                    if fra:
                        final_right_answer_list.append(fra)

                # 辅助函数：将列表格式化为字符串（去括号、引号，替换分号）
                def format_list(lst):
                    if not lst:
                        return None
                    # 将列表元素转为字符串并用分号连接，同时替换中文分号
                    return ";".join([str(x) for x in lst]).replace("；", ";")

                # 辅助函数：计算耗时（不记录天数小时，超过1小时记为beyond1h）
                def calculate_duration(start_str, end_str):
                    if not start_str or not end_str:
                        return None
                    try:
                        start = pd.to_datetime(start_str)
                        end = pd.to_datetime(end_str)
                        delta = end - start
                        total_seconds = delta.total_seconds()

                        if total_seconds > 3600:
                            return "beyond1h"

                        # 格式化为 MM:SS.mmm
                        minutes = int(total_seconds // 60)
                        seconds = int(total_seconds % 60)
                        millis = int(delta.microseconds / 1000)
                        return f"{minutes:02}:{seconds:02}.{millis:03}"
                    except:
                        return None

                result_data = {
                    "is_right_parts": str(is_right_parts_list) if is_right_parts_list else None,
                    # "question_category": " | ".join(question_category_list) if question_category_list else None,
                    "question_type": " | ".join(question_type_list) if question_type_list else None,
                    "question": " | ".join([str(q) for q in question_list]) if question_list else None,
                    "user_answer": format_list(user_answer_list),
                    "user_final_answer": format_list(user_final_answer_list),
                    "final_right_answer": format_list(final_right_answer_list),
                    "实际处理耗时": calculate_duration(data.get("processing_at"), data.get("updated_at"))
                }
                return "completed", result_data

            elif state == "failed":
                return "failed", None

            else:
                return "processing", None

        except Exception as e:
            print(f"{img_name} - 请求异常: {str(e)}")
            return "processing", None # 异常视作处理中，等待重试

    def batch_poll(self, df, timeout_minutes, interval_seconds, failed_output_path=None):
        """
        轮询所有任务直到完成或超时
        """
        # 过滤有效数据
        df_valid = df.dropna(subset=["图片名称", "task ID"]).copy()
        pending_tasks = {
            row["图片名称"]: row["task ID"]
            for _, row in df_valid.iterrows()
        }

        results = {} # Store results for completed tasks
        failed_tasks = []

        start_time = time.time()
        end_time = start_time + timeout_minutes * 60

        print(f"开始轮询，共 {len(pending_tasks)} 个任务，超时时间 {timeout_minutes} 分钟，间隔 {interval_seconds} 秒")

        while pending_tasks:
            current_time = time.time()
            if current_time > end_time:
                print("轮询超时！")
                break

            print(f"当前剩余任务数: {len(pending_tasks)}")

            # 本轮检查
            completed_in_this_round = []
            failed_in_this_round = []
            processing_count = 0

            # 使用线程池并发检查状态
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_img = {
                    executor.submit(self.check_task_status, task_id, img_name): img_name
                    for img_name, task_id in pending_tasks.items()
                }

                for future in future_to_img:
                    img_name = future_to_img[future]
                    try:
                        status, data = future.result()
                        if status == "completed":
                            results[img_name] = data
                            completed_in_this_round.append(img_name)
                        elif status == "failed":
                            failed_in_this_round.append(img_name)
                        else:
                            processing_count += 1
                    except Exception as e:
                        print(f"{img_name} - 轮询异常: {e}")

            # 更新pending列表
            for img in completed_in_this_round:
                del pending_tasks[img]

            for img in failed_in_this_round:
                del pending_tasks[img]
                failed_tasks.append(img)

            # 输出本轮统计
            print(f"本轮结果: Completed={len(completed_in_this_round)}, Failed={len(failed_in_this_round)}, Processing/Other={processing_count}")

            if not pending_tasks:
                break

            # 等待下一轮
            print(f"等待 {interval_seconds} 秒后进行下一轮轮询...")
            time.sleep(interval_seconds)

        # 结果汇总
        print(f"轮询结束。成功: {len(results)}, 失败: {len(failed_tasks)}, 未完成: {len(pending_tasks)}")

        # 保存失败列表（始终写入：若全部成功则写入空数组[]，避免残留旧数据）
        if failed_output_path:
            all_failed = failed_tasks + list(pending_tasks.keys())
            try:
                os.makedirs(os.path.dirname(os.path.abspath(failed_output_path)), exist_ok=True)
                with open(failed_output_path, "w", encoding="utf-8") as f:
                    json.dump(all_failed, f, ensure_ascii=False, indent=4)
                print(f"失败/未完成任务列表（{len(all_failed)} 项）已保存至: {failed_output_path}")
            except Exception as e:
                print(f"保存失败列表失败: {e}")
        return results, failed_tasks + list(pending_tasks.keys())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--task_excel", type=str, required=True, help="含task ID的Excel路径")
    parser.add_argument("-o", "--output_excel", type=str, required=True, help="输出结果Excel路径")
    parser.add_argument("-rurl", "--result_url", type=str, default=os.getenv("RESULT_BASE_URL"), help="结果接口基地址；默认读取 RESULT_BASE_URL")
    parser.add_argument("-bt", "--bearer_token", type=str, default=os.getenv("BEARER_TOKEN"), help="Bearer Token；默认读取 BEARER_TOKEN")
    parser.add_argument("-rp", "--raw_path", type=str, default="./data/raw_results", help="raw txt response save path")
    parser.add_argument("-to", "--timeout", type=int, default=DEFAULT_TIMEOUT, help="timeout in minutes")
    parser.add_argument("-int", "--interval", type=int, default=DEFAULT_INTERVAL, help="poll interval in seconds")
    parser.add_argument("-fo", "--failed_output", type=str, help="failed images json output path")

    # 兼容旧参数（如果有）
    parser.add_argument("-vp", "--vis_path", type=str, help="Visualization path (ignored)")
    parser.add_argument("-q", "--query_file", type=str, help="Query file (ignored)")
    parser.add_argument("-m", "--max_retries", type=str, help="Max retries (ignored)")

    args = parser.parse_args()
    if not args.result_url:
        parser.error("请提供 --result_url 或设置 RESULT_BASE_URL")
    if not args.bearer_token:
        parser.error("请提供 --bearer_token 或设置 BEARER_TOKEN")

    # 1. 读取Excel
    try:
        df = pd.read_excel(args.task_excel)
        print(f"读取Excel: {args.task_excel}, 共 {len(df)} 行")
    except Exception as e:
        print(f"读取Excel失败: {e}")
        return

    # 2. 初始化Fetcher
    fetcher = TaskResultFetcher(
        api_url=args.result_url,
        bearer_token=args.bearer_token,
        txt_save_path=args.raw_path
    )

    # 3. 轮询
    results, failed_imgs = fetcher.batch_poll(
        df,
        timeout_minutes=args.timeout,
        interval_seconds=args.interval,
        failed_output_path=args.failed_output
    )

    # 4. 填充结果
    def get_field(img_name, field):
        if img_name in results and results[img_name]:
            return results[img_name].get(field)
        return None

    df["is_right_parts"] = df["图片名称"].apply(lambda x: get_field(x, "is_right_parts"))
    df["question_type"] = df["图片名称"].apply(lambda x: get_field(x, "question_type"))
    df["question"] = df["图片名称"].apply(lambda x: get_field(x, "question"))
    df["user_answer"] = df["图片名称"].apply(lambda x: get_field(x, "user_answer"))
    df["user_final_answer"] = df["图片名称"].apply(lambda x: get_field(x, "user_final_answer"))
    df["final_right_answer"] = df["图片名称"].apply(lambda x: get_field(x, "final_right_answer"))
    df["实际处理耗时"] = df["图片名称"].apply(lambda x: get_field(x, "实际处理耗时"))

    # 标记失败的
    if failed_imgs:
        df.loc[df["图片名称"].isin(failed_imgs), "is_right_parts"] = "failed"
        df.loc[df["图片名称"].isin(failed_imgs), "question_type"] = "failed"
        df.loc[df["图片名称"].isin(failed_imgs), "question"] = "failed"
        df.loc[df["图片名称"].isin(failed_imgs), "user_answer"] = "failed"
        df.loc[df["图片名称"].isin(failed_imgs), "user_final_answer"] = "failed"
        df.loc[df["图片名称"].isin(failed_imgs), "final_right_answer"] = "failed"
        df.loc[df["图片名称"].isin(failed_imgs), "实际处理耗时"] = "failed"

    # 5. 保存
    try:
        df.to_excel(args.output_excel, index=False)
        print(f"结果已保存至: {args.output_excel}")
    except Exception as e:
        print(f"保存Excel失败: {e}")

    # Exit with code 1 if there are failures, so shell script knows
    if failed_imgs:
        sys.exit(1)

if __name__ == "__main__":
    main()
