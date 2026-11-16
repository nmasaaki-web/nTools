# 教員向け：nToolsの公開・管理

## 初回公開

このZIPを解凍し、`nTools_repository` フォルダの**中身**を、既存のローカルGitリポジトリ（例：`~/Documents/git/nTools`）へコピーする。既存の `.git` フォルダは削除しない。`README.md` が既にある場合は今回の版で置き換える。

Git Bashをそのリポジトリで開き、次を実行する。

```bash
git status
git remote -v
git add README.md install.py release.py version.json .gitignore .gitattributes scripts docs
git commit -m "Add nTools Maya shelf and four tools"
git push -u origin main
```

originが `https://github.com/nmasaaki-web/nTools.git` であることを確認する。未設定の場合のみ `git remote add origin https://github.com/nmasaaki-web/nTools.git`。Gitの初回設定がまだなら `git config --global user.name "nmasaaki-web"` と `git config --global user.email "自分のGitHubメールアドレスまたはnoreply"` を実行する。

公開後、GitHubのREADMEが表示され、Code → Download ZIPで全ファイルを入手できることを確認する。学生にはリポジトリURLを案内する。

## 更新の流れ

1. `scripts/ntools/tools/` の該当Pythonファイルを最新版に置き換える。ファイル名は固定する。
2. `release.py` の `TOOLS` 内で該当ツールの `version` を更新する。起動関数が変わった場合は `entry`、importで自動起動するか変わった場合は `opens_on_import` も調整する。
3. ルートの `README.md` のバージョン表も更新する。
4. リポジトリルートで通常のPython 3を使用し、`python release.py 1.0.1` を実行する（Windowsで必要なら `py -3 release.py 1.0.1`、macOSなら `python3 release.py 1.0.1`）。リリース番号は必ず前回より大きくする。
5. `version.json` に全配布ファイルのSHA-256が生成される。内容を確認したうえでまとめてコミット・pushする。

```bash
git add scripts install.py release.py version.json README.md docs
git commit -m "Release nTools 1.0.1"
git push
```

学生側はUpdateボタンだけで更新できる。ZIPを再配布する必要はない。`version.json` を更新しないままスクリプトだけ変更すると検証が失敗するので、必ずrelease.pyを実行する。

## シェルフ構成

`release.py` の `TOOLS` の並び順がシェルフの順番になる。追加・削除・並び替えの後は必ずリリース番号を上げて `release.py` を実行する。Updateは自動的に最後に付く。アイコンは64×64 PNG。初回導入時に自動登録されるため手動でMELシェルフを配布する必要はない。

## 動作確認チェックリスト（配布前）

- WindowsのMaya 2027で新規ユーザー環境にインストール、5ボタン、ツール起動、再起動後の残存を確認。
- macOSのMaya 2027でも同様に確認。PolyHavenとSketchfabのネットワーク通信を確認。
- GitHub mainに新バージョンを公開し、旧版インストール済み環境でUpdate → 確認 → 再起動を確認。
- 他のシェルフ、シーン、プロジェクトデータが変更されていないことを確認。
- 失敗テスト：ネットワーク切断、壊れたハッシュ、同一バージョン、既存nTools名のシェルフ。エラー表示と旧版維持を確認。
- QQRでリグ生成・IK/FK・転送をコピーしたシーンで確認。特に旧版の制約を継承する。

## 技術メモ

- `install.py` を展開したリポジトリから実行する場合はローカルファイルを使用。単体で実行した場合は公開GitHub mainのZIPを取得する。
- `scripts/ntools` の内容とインストーラー自身を `cmds.internalVar(userScriptDir=True)/ntools` に導入する。
- シェルフは `cmds.internalVar(userShelfDir=True)/shelf_nTools.mel` に保存する。コマンドはクリック時に環境別のスクリプトパスを解決する。
- 更新は同一GitHubアーカイブのマニフェストと照合し、SHA-256およびPython構文を検証してから既存フォルダを置換する。ハッシュは転送・構成ミスの検出用で、署名ではない。GitHubの管理者アカウントとmainへの書き込み権限を保護すること。
- 更新直後は旧Pythonモジュールがメモリに残る可能性があるので再起動が必要。直前のパッケージは `.ntools-backup-*` に1世代保存する。手動復元時はMayaを終了してから実施する。
- 既存nToolsシェルフに学生が追加した個人ボタンは更新で消える。個人用ボタンは別のシェルフへ移動すること。未管理のnToolsシェルフと衝突した場合は初回導入を中止する。
- 問題がある場合はScript EditorのログとOS、Mayaのバージョンを教員へ知らせる。
