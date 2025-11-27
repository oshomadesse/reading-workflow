#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Sheets 除外本リスト取得モジュール（効率化版）
作成日: 2025年8月7日
"""

import requests
import csv
from io import StringIO
from typing import List

class SheetsConnector:
    """Google Sheets接続・データ取得クラス（公開版）"""
    
    def __init__(self, spreadsheet_id: str = None, sheet_gid: str = None):
        self.spreadsheet_id = spreadsheet_id or "1aZ9VkAE3ZMfc6tkwfVPjolMZ4DU6SwodBUc2Yd13R10"
        self.sheet_gid = sheet_gid or "638408503"
        self.export_url = f"https://docs.google.com/spreadsheets/d/{self.spreadsheet_id}/export?format=csv&gid={self.sheet_gid}"
    
    def get_excluded_books(self) -> List[str]:
        """除外本リスト取得"""
        try:
            print(f"📊 公開スプレッドシートにアクセス中...")
            response = requests.get(self.export_url)
            
            if response.status_code != 200:
                print(f"❌ アクセス失敗 ステータス: {response.status_code}")
                return []
            
            print(f"✅ スプレッドシートアクセス成功")
            
            response.encoding = 'utf-8'
            reader = csv.reader(StringIO(response.text))
            rows = list(reader)
            
            print(f"📊 取得行数: {len(rows)}行")
            
            excluded_books = []
            for i, row in enumerate(rows):
                if len(row) > 1 and i > 0:  # B列存在 & ヘッダー行スキップ
                    book_title = row[1].strip()
                    if book_title and not any(keyword in book_title for keyword in ['書籍', 'タイトル', 'Book', '回答', 'タイムスタンプ']):
                        excluded_books.append(book_title)
            
            # ✅ は統合側で出すのでここでは削除
            if excluded_books:
                print("   除外本例:")
                for i, book in enumerate(excluded_books[:5]):
                    print(f"     {i+1}. {book}")
                if len(excluded_books) > 5:
                    print(f"     ... 他{len(excluded_books)-5}冊")
            
            return excluded_books
                
        except Exception as e:
            print(f"❌ 除外本リスト取得エラー: {e}")
            return []
    
    def get_worksheet_info(self) -> dict:
        """ワークシート情報取得"""
        try:
            response = requests.get(self.export_url)
            response.encoding = 'utf-8'
            rows = list(csv.reader(StringIO(response.text))) if response.status_code == 200 else []
            
            return {
                'spreadsheet_id': self.spreadsheet_id,
                'sheet_gid': self.sheet_gid,
                'access_method': 'public_csv_export',
                'total_rows': len(rows),
                'status': 'success' if response.status_code == 200 else 'failed'
            }
        except Exception as e:
            return {'spreadsheet_id': self.spreadsheet_id, 'status': 'error', 'error': str(e)}

def get_excluded_books() -> List[str]:
    """除外本リスト取得（シンプル関数）"""
    try:
        return SheetsConnector().get_excluded_books()
    except Exception as e:
        print(f"❌ 除外本リスト取得エラー: {e}")
        return []

def test_sheets_connector():
    """sheets_connector.py 単体テスト"""
    print("🧪 Google Sheets Connector テスト開始（公開アクセス版）")
    print("="*50)
    
    try:
        connector = SheetsConnector()
        
        print("📊 ワークシート情報:")
        info = connector.get_worksheet_info()
        if info.get('status') == 'success':
            print(f"   スプレッドシートID: {info.get('spreadsheet_id')}")
            print(f"   アクセス方法: {info.get('access_method')}")
            print(f"   総行数: {info.get('total_rows')}行")
        
        print("\n📚 除外本リスト取得テスト:")
        excluded_books = connector.get_excluded_books()
        
        if excluded_books and len(excluded_books) >= 20:
            print(f"✅ 成功: {len(excluded_books)}冊取得（期待値24冊）")
            return True
        else:
            print(f"⚠️  取得数が期待値と異なります: {len(excluded_books)}冊（期待値24冊）")
            return False
            
    except Exception as e:
        print(f"❌ テストエラー: {e}")
        return False

if __name__ == "__main__":
    test_sheets_connector()
