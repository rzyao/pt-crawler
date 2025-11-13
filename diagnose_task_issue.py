#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断任务创建问题的测试脚本
"""
import requests
import json
import traceback

def test_simple_task_creation():
    """简化版任务创建测试"""
    
    print("=== 简化任务创建测试 ===")
    
    # 获取站点列表
    try:
        response = requests.get("http://localhost:8000/sites")
        sites = response.json()
        print(f"站点列表响应: {sites}")
        
        if not sites:
            print("❌ 没有可用的站点")
            return False
        
        site_id = sites[0]['id']
        print(f"使用站点ID: {site_id}")
        
    except Exception as e:
        print(f"❌ 获取站点列表失败: {e}")
        print(f"错误详情: {traceback.format_exc()}")
        return False
    
    # 最简化的任务数据
    print("\n创建最简单的任务:")
    task_data = {
        "name": "测试",
        "site_id": site_id,
        "schedule_type": "interval", 
        "schedule_value": "3600"
    }
    
    print(f"发送数据: {json.dumps(task_data, ensure_ascii=False)}")
    
    try:
        response = requests.post(
            "http://localhost:8000/tasks/",
            json=task_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应头: {dict(response.headers)}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ 任务创建成功: {result}")
            return True
        else:
            print(f"❌ 任务创建失败: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"❌ 连接错误: {e}")
        return False
    except Exception as e:
        print(f"❌ 其他错误: {e}")
        print(f"错误详情: {traceback.format_exc()}")
        return False

def test_backend_health():
    """测试后端健康状态"""
    
    print("\n=== 后端健康检查 ===")
    
    endpoints = [
        ("站点列表", "/sites"),
        ("任务列表", "/tasks"),
        ("种子列表", "/torrents")
    ]
    
    for name, endpoint in endpoints:
        try:
            response = requests.get(f"http://localhost:8000{endpoint}", timeout=5)
            print(f"{name}: {response.status_code}")
            
            if response.status_code != 200:
                print(f"  错误响应: {response.text[:200]}")
                
        except Exception as e:
            print(f"{name}: 失败 - {e}")

if __name__ == "__main__":
    print("开始诊断任务创建问题...")
    
    # 1. 检查后端健康状态
    test_backend_health()
    
    # 2. 测试简单任务创建
    test_simple_task_creation()
    
    print("\n诊断完成。请检查服务器日志获取更多信息。")