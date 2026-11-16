# nTools 管理者向けガイド v1.0.5

## 公開・移行

ZIPの中身を既存のGit作業フォルダに上書きコピーする。`.git` は維持する。`git status` を確認し、以下を実行する。

```bash
git add .
git commit -m "Release nTools v1.0.5 - safer installer"
git push
```

v1.0.0〜1.0.2から移行する場合は、旧Updateを使用せず、新ZIPのinstall.pyから導入する。異常なタブ名がある場合はREADMEの復旧手順を先に実施。

## 実機検証手順（Windows / macOS）

1. Mayaの設定フォルダをMaya終了中に別の場所へコピーし、復旧できるようにする。既存の制作シーンは保存する。可能なら検証専用OSユーザーを使用する。
2. 起動してFile等のメニュー、メニューセット、他シェルフを確認。新規環境でInstall + Shelfを選択する（Files Onlyによる段階テストも可能）。
3. 再起動せず4ツール、Help、Uninstall、Updateを確認し、各ツールの起動を試す。Files Onlyを選んだ場合は管理コードからRepair Shelfを選択する。
4. Maya再起動後にシェルフが残ること、File等のメニューが表示されることを確認。
5. Updateボタンで最新版判定を確認。次のテスト版を公開して更新するとき、既存シェルフのボタン数・順序、メニューが変化しないことを確認。
6. Uninstallは2段階：案内ウィンドウで「コピー」を押し、コードがクリップボードに入ることを確認。メモ帳などに保存してからMaya標準Shelf EditorでnToolsだけを削除・保存し再起動。Pythonタブでコピーしたコードを実行し、確認後に本体をバックアップへ移動する。自動シェルフ削除は行わない。

## 変更履歴と設計

- 1.0.0: 初回配布。通常更新でもシェルフを再構築。
- 1.0.1: パッケージ置換をシェルフ操作から分離。既存タブは再構築しない。修復は欠落タブに限定。Maya公式addNewShelfTab / deleteShelfTabを使用し、独自deleteUIでタブを削除しない。メニューセットを読み取り確認し、関連設定をバックアップ。全体設定の自動リセットなし。
- 1.0.2: Uninstallボタンを追加。
- 1.0.3: saveShelfの二重拡張子問題を修正。異常なシェルフ名・ファイルを検出して中止。Uninstallは標準Shelf Editorを使う2段階方式に変更。
- 1.0.4: 初回のInstall + Shelfを既定にし、再起動不要と明記。Uninstall案内をコード欄・コピーボタン付きQtダイアログに変更。削除処理は1.0.3の安全な2段階方式を維持。
- 1.0.5: 4ツールの右上に個別Help、シェルフにHelp（Uninstallの左）を追加。ツールの主要処理と既存アイコンは維持。旧5・6ボタンからAdd Help Buttonで明示的に移行。マニュアルに操作図・GIF・MP4と実機撮影ガイドを追加。

## 次のリリース

ツール本体を `scripts/ntools/tools/` 内の該当ファイルで上書きする。必要に応じ `release.py` のTOOLSリストでバージョン、説明等を修正する。アイコンは `scripts/ntools/icons/` に配置。配布に含めるファイルのハッシュを生成する：

```bash
python release.py 1.0.4
git add .
git commit -m "Release nTools v1.0.5"
git push
```

更新時はバージョン番号を必ず増加させる。v1.0.5のHelp追加だけなら更新後再起動し、Add Help Buttonで移行する。将来の新しいツールの追加・削除やボタンの順序・説明・アイコンファイル名変更がある場合、学生は更新後に既存nToolsタブをMayaのShelf Editorで削除・保存し、再起動後Repair Shelfを実行する。通常のツール本体変更だけなら不要。既存ボタンの説明やバージョン表記（旧版シェルフ）は自動更新されない。

## 復旧

- ファイル更新中の失敗では、旧パッケージへの復元を試みる。失敗ログとバックアップのパスをScript Editorで確認する。
- 新規シェルフ登録中に問題が発生した場合、本体を保持する。部分的なシェルフを自動削除しない。MayaのUIが正常ならShelf EditorでnToolsだけを整理する。
- UIバックアップは `cmds.internalVar(userScriptDir=True)` の `.ntools-ui-backups` にある。必要に応じてMaya終了中に、現行設定を別途バックアップしてから復元する。自動復元は行わない。バックアップ対象は存在するuserPrefs.mel、menuSetPrefs.mel、windowPrefs.mel、userHotkeys.mel、shelf_nTools.mel。完全なprefsバックアップではない。
- Maya.envを編集する処理はない。設定の破損原因が特定できない場合、Mayaの設定フォルダ全体を別名に変更して再起動し、必要な設定のみ戻す。
- アンインストール後の本体バックアップは `.ntools-uninstalled-*`。手動復元するならMayaを終了し、既存ntoolsフォルダがないことを確認してから名前をntoolsに戻し、再起動後Repair Shelf。

## 検証範囲

Python構文、ハッシュ、ZIP、ファイル置換、模擬Maya APIによる処理のテストを実施可能。実際のMaya 2027.2のUI動作、再起動後の保持、Mac環境およびGitHub接続は実機検証が必要。

旧版の復旧手順とv1.0.5の検証条件はREADMEを参照。`saveShelf` の保存先は拡張子なしとする。
