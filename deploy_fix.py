#!/usr/bin/env python3
"""VPS 上で実行: app.py の deep_dive_result に marketing 初期化を追加"""
path = "app.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# パターン1: try の直前に追加（古いコード）
old1 = '''    @app.post("/deep_dive/result")
    def deep_dive_result():
        try:
            scores = score_answers_from_form(request.form)'''
new1 = '''    @app.post("/deep_dive/result")
    def deep_dive_result():
        _default_marketing = {"empathy": "", "problem": "", "cause": "", "solution": "", "future": ""}
        marketing = dict(_default_marketing)
        try:
            scores = score_answers_from_form(request.form)'''

if "marketing = dict(_default_marketing)" in content:
    print("OK: 既に修正済みです")
elif old1 in content:
    content = content.replace(old1, new1, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: app.py を修正しました")
else:
    print("SKIP: パターンが一致しません")
