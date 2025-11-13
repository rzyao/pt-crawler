#!/usr/bin/env python3
# -*- coding: utf -*-
"""
调试表单提交的测试脚本
用于检查前端发送的数据和后端接收的数据
"""
import requests
import json

def test_site_submission():
    """测试站点添加功能，模拟前端发送的数据"""
    
    # 测试数据 - 模拟前端表单提交的数据
    test_data = {
        "name": "测试站点",
        "base_url": "https://example.com",
        "list_path": "/torrents",
        "cookie": "test_cookie_value"
    }
    
    print("=== 测试站点添加功能 ===")
    print(f"发送的数据: {json.dumps(test_data, ensure_ascii=False, indent=2)}")
    
    try:
        # 发送POST请求到后端
        response = requests.post(
            "http://localhost:8000/sites/",
            json=test_data,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"成功添加站点，ID: {result.get('id')}")
        else:
            print(f"添加失败: {response.text}")
            
    except Exception as e:
        print(f"请求失败: {e}")

def test_missing_fields():
    """测试缺少必填字段的情况"""
    
    print("\n=== 测试缺少必填字段 ===")
    
    # 测试缺少name字段
    test_data_missing_name = {
        "base_url": "https://example.com",
        "list_path": "/torrents"
    }
    
    print(f"发送的数据（缺少name）: {json.dumps(test_data_missing_name, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(
            "http://localhost:8000/sites/",
            json=test_data_missing_name,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
    except Exception as e:
        print(f"请求失败: {e}")
    
    # 测试缺少base_url字段
    test_data_missing_url = {
        "name": "测试站点",
        "list_path": "/torrents"
    }
    
    print(f"\n发送的数据（缺少base_url）: {json.dumps(test_data_missing_url, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(
            "http://localhost:8000/sites/",
            json=test_data_missing_url,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
    except Exception as e:
        print(f"请求失败: {e}")

def test_with_user_agent():
    """测试包含User-Agent字段的情况"""
    
    print("\n=== 测试包含User-Agent字段 ===")
    
    test_data_with_ua = {
        "name": "测试站点带UA",
        "base_url": "https://example.com",
        "list_path": "/torrents",
        "cookie": "test_cookie_value",
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    print(f"发送的数据: {json.dumps(test_data_with_ua, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(
            "http://localhost:8000/sites/",
            json=test_data_with_ua,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"响应状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"成功添加站点，ID: {result.get('id')}")
        else:
            print(f"添加失败: {response.text}")
            
    except Exception as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    test_site_submission()
    test_missing_fields()
    test_with_user_agent()