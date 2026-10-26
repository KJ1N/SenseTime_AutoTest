#图片URL发送至接口以获取task ID
import sys
import os
from io import BytesIO
from pathlib import Path
import base64
import json
import requests
import time

import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from PIL import ImageOps
import pandas as pd
import argparse


class MathGrade:
    def __init__(self, API_URL, bearer_token=None,SLEEP_TIME=0.5):
        self.API_URL = API_URL
        self.bearer_token = f"Bearer {bearer_token}" if bearer_token else ""
        self.SLEEP_TIME=SLEEP_TIME

    def flush(self):
        """确保并发时stdout和stderr清空"""
        sys.stdout.flush()
        sys.stderr.flush()

    def build_query(self, result_dict, key_list, val_list):
        """批量执行请求，填充result_dict的task_id"""
        with ThreadPoolExecutor(max_workers=4) as executor:
            executor.map(
                self._build_query,
                [result_dict] * len(key_list),
                key_list,
                val_list
            )
        self.flush()

    def _build_query(self, result_dict, result_key, image_url):
        """单条请求逻辑：直接用URL构造payload，获取task_id"""
        try:
            # 构造URL格式的payload
            images = [{
                "image_type": "url",
                "image": image_url  # 直接使用传入的URL（非列表）
            }]
            headers = {
                "Content-Type": "application/json",
                "Authorization": self.bearer_token
            }
            play_load = {
                "enable_time_debug": True,
                "thinking": True,
                "image_enhance": False,
                "images": images,
                "subject":"1"
            }
            '''
            play_load = {
                "images": images,
            }
            '''
            # 请求休眠，避免高频调用
            time.sleep(self.SLEEP_TIME)
            # 发送POST请求
            response = requests.post(
                self.API_URL,
                headers=headers,
                data=json.dumps(play_load, ensure_ascii=False),
                timeout=60
            )
            response.raise_for_status()  # 触发HTTP错误（如404/500）
            response_json = response.json()

            # 提取task_id
            task_id = response_json["data"]["task_id"]
            #print(f"{result_key} 处理成功，task_id: {task_id}")
            result_dict[result_key] = task_id

        except Exception as e:
            print(f"{result_key} 处理失败: {type(e).__name__}")
            print(f"  异常类型: {type(e).__name__}")
            print(f"  响应状态码: {response.status_code if 'response' in locals() else '无'}")
            result_dict[result_key] = None

def get_image_info_from_excel(excel_path):
    """从原Excel读取图片名称和对应的图片URL"""
    try:
        df = pd.read_excel(excel_path)
        # 校验必要列
        required_cols = ["图片名称", "图片URL"]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Excel缺少必要列：{missing_cols}")

        # 过滤空值行（图片名称或URL为空则跳过）
        df_valid = df.dropna(subset=required_cols).copy()
        # 去重（按图片名称去重，保留第一条）
        df_valid = df_valid.drop_duplicates(subset=["图片名称"], keep="first")

        # 构建 图片名称: 图片URL 的字典
        img_name_to_url = dict(zip(df_valid["图片名称"], df_valid["图片URL"]))
        print(f"从Excel {excel_path} 读取到 {len(img_name_to_url)} 条有效图片名称+URL数据")
        return df, img_name_to_url
    except Exception as e:
        print(f"读取Excel失败: {str(e)}")
        return None, {}

def main(args):
    SLEEP_TIME=args.sleep_time
    ROOT_EXCEL=args.url_excel
    API_URL=args.judge_url
    OUTPUT_EXCEL=args.taskid_excel
    BEARER_TOKEN=args.bearer_token
    # 1. 读取原Excel，获取图片名称和对应的URL
    df_original, img_name_to_url = get_image_info_from_excel(ROOT_EXCEL)
    if df_original is None or df_original.empty or not img_name_to_url:
        print("未从Excel读取到有效图片名称+URL数据，程序退出")
        return False

    # 2. 加载已处理的task_id（断点续跑）
    taskid_json_path = os.path.join(os.path.dirname(ROOT_EXCEL), "task_id_cache.json")
    task_id_sets = {}
    if os.path.exists(taskid_json_path):
        try:
            with open(taskid_json_path, "r", encoding="utf-8") as f:
                task_id_sets = json.load(f)
            # 过滤已处理的图片
            img_name_to_url = {k: v for k, v in img_name_to_url.items() if k not in task_id_sets}
            print(f"断点续跑 - 过滤后待处理图片数量: {len(img_name_to_url)}")
        except Exception as e:
            print(f"加载缓存的task_id失败: {str(e)}")
            task_id_sets = {}

    # 3. 批量获取task_id（仅处理未完成的）
    if len(img_name_to_url) > 0:
        # 初始化MathGrade
        math_module = MathGrade(API_URL=API_URL, bearer_token=BEARER_TOKEN,SLEEP_TIME=SLEEP_TIME)
        result_data = {}
        # 准备并发参数：图片名列表 + URL列表
        key_list = list(img_name_to_url.keys())
        val_list = list(img_name_to_url.values())
        # 执行请求
        math_module.build_query(result_data, key_list, val_list)

        # 4. 更新task_id缓存
        task_id_sets.update(result_data)
        try:
            with open(taskid_json_path, "w", encoding="utf-8") as f:
                json.dump(task_id_sets, f, ensure_ascii=False, indent=4)
            print(f"task_id缓存已保存至: {taskid_json_path}")
        except Exception as e:
            print(f"保存task_id缓存失败: {str(e)}")
    else:
        print("所有图片已处理完成，直接使用缓存生成最终Excel")

    # 5. 给原Excel追加Task ID列
    try:
        # 确保输出目录存在
        output_dir = os.path.dirname(OUTPUT_EXCEL)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)
            print(f"已创建目录: {output_dir}")

        # 映射：图片名称 -> task_id（未找到则为None）
        df_original["task ID"] = df_original["图片名称"].map(task_id_sets)
        # 保存新Excel
        df_original.to_excel(OUTPUT_EXCEL, index=False)
        print(f"带Task ID的新Excel已生成: {OUTPUT_EXCEL}")
    except Exception as e:
        print(f"生成新Excel失败: {str(e)}")
        return False

    # 6. 统计失败情况
    failed_imgs = [k for k, v in task_id_sets.items() if v is None]
    if failed_imgs:
        print(f"\n处理失败的图片列表: {failed_imgs}")
        print(f"总计失败数量: {len(failed_imgs)}")
    else:
        print("\n所有图片处理成功！")

    return len(failed_imgs) > 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-te", "--taskid_excel", type=str, help="含task ID的excel")
    parser.add_argument("-ue", "--url_excel", type=str, required=True, help="生成url的Excel保存路径")
    parser.add_argument("-st", "--sleep_time", type=float, default=0.5, help="每次请求休眠时间（秒）")
    parser.add_argument("-ju", "--judge_url", type=str, default=os.getenv("JUDGE_URL"), help="任务提交接口；默认读取 JUDGE_URL")
    parser.add_argument("-bt", "--bearer_token", type=str, default=os.getenv("BEARER_TOKEN"), help="权限token；默认读取 BEARER_TOKEN")
    parser.add_argument("-cc", "--clean_cache", type=str, help="clean cache for failed images json file path")
    args = parser.parse_args()

    if args.clean_cache:
        try:
            with open(args.clean_cache, "r", encoding="utf-8") as f:
                failed_imgs = json.load(f)

            taskid_json_path = os.path.join(os.path.dirname(args.url_excel), "task_id_cache.json")
            if os.path.exists(taskid_json_path):
                with open(taskid_json_path, "r", encoding="utf-8") as f:
                    task_id_sets = json.load(f)

                original_count = len(task_id_sets)
                for img in failed_imgs:
                    if img in task_id_sets:
                        del task_id_sets[img]

                with open(taskid_json_path, "w", encoding="utf-8") as f:
                    json.dump(task_id_sets, f, ensure_ascii=False, indent=4)
                print(f"Cleaned {original_count - len(task_id_sets)} failed images from cache.")
            sys.exit(0)
        except Exception as e:
            print(f"Failed to clean cache: {e}")
            sys.exit(1)

    if not args.taskid_excel:
        parser.error("正常执行时必须提供 --taskid_excel")
    if not args.judge_url:
        parser.error("请提供 --judge_url 或设置 JUDGE_URL")
    if not args.bearer_token:
        parser.error("请提供 --bearer_token 或设置 BEARER_TOKEN")

    ### main process
    sys.exit(1 if main(args) else 0)

    print("Done!")
