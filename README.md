# nTools v1.0.5

Maya向け授業用ツールセット。Windows / macOS、Maya 2027（Arnold / OpenPBR利用環境）を想定。実機での動作確認は配布前に行ってください。

![nTools shelf preview](docs/shelf_preview.png)

## ツールの使い方（学生向け）

アイコンまたはツール名をクリックすると、日本語の操作マニュアルを開けます。実際のUIに合わせた手順、設定の意味、よくあるエラーを掲載しています。

| アイコン | ツール・操作マニュアル | バージョン | 機能 |
|---|---|---|---|
| [![SF](scripts/ntools/icons/sketchfab.png)](docs/tools/sketchfab.md) | [Sketchfab Asset Browser](docs/tools/sketchfab.md) | 1.2 | 静的glTFモデルの検索・インポート、OpenPBR |
| [![PH](scripts/ntools/icons/polyhaven.png)](docs/tools/polyhaven.md) | [PolyHaven Asset Browser](docs/tools/polyhaven.md) | 5.2 | モデル・テクスチャ・HDRI、ローカルライブラリ |
| [![MAT](scripts/ntools/icons/material.png)](docs/tools/material_creator.md) | [Material Creator](docs/tools/material_creator.md) | 1.3 | ローカルテクスチャ / JSONからOpenPBR作成 |
| [![RIG](scripts/ntools/icons/quadruped.png)](docs/tools/quadruped.md) | [Quadruped Quick Rig](docs/tools/quadruped.md) | 2.4.0 | 四足ガイド、IK/FK、試験的なリターゲット |

> v1.0.5では各ツール右上にHelpを追加し、シェルフにHelpを追加しました。各マニュアルに操作図・GIF・MP4を掲載しています（実機キャプチャではありません）。既存のv1.0.4からはUpdate → Maya再起動 → Add Help Buttonで移行できます。

## 初回導入（学生）

1. [GitHub](https://github.com/nmasaaki-web/nTools) の Code → Download ZIP を選択し、展開する。
2. Mayaを起動し、Fileメニュー・メニューセット・シェルフが正常に表示されていることを確認。作業中のシーンを保存する。
3. 展開した `install.py` をMayaのビューポートへドラッグ＆ドロップ。確認画面で **Install + Shelf** を選ぶと、未登録の場合に限りnToolsシェルフを作成する。**Files Only** は本体だけを導入する（安全確認用）。
4. 初回導入は再起動不要。nToolsタブを選び、4ツール、Help、Uninstall、右端Updateをすぐに使用できる。初回の実機検証では後から再起動してシェルフの保持も確認する。

ドラッグできない場合はScript Editorの **Python** タブで実行し、展開した `install.py` を選択：

```python
import maya.cmds as cmds
import runpy
p = cmds.fileDialog2(fileMode=1, fileFilter='Python (*.py)', caption='Select nTools install.py') or []
if p:
    runpy.run_path(p[0], run_name='__main__')
```

## 旧版 v1.0.0 からの移行（重要）

旧版のUpdateはシェルフを再登録するため、**旧版のUpdateを押さず**、v1.0.5のZIPをダウンロードして上記のインストールを行う。まずFiles Onlyを選択し、Mayaを再起動してUIが正常か確認することを推奨。既存のnToolsシェルフは変更しない。タブがない場合は次のRepair Shelfを実行する。

## 管理・修復・アンインストール

Maya Script EditorのPythonタブで実行：

```python
import sys
import maya.cmds as cmds
p = cmds.internalVar(userScriptDir=True)
if p not in sys.path:
    sys.path.insert(0, p)
from ntools import installer as nt
nt.manage()
```

- **Update**：GitHub mainの新しいバージョンを確認し、本体だけ更新。既存シェルフは一切変更しない。更新後は再起動。
- **Repair Shelf**：シェルフが存在しないときにだけ登録。既存タブは変更しない。既存のタブを作り直したい場合はMaya標準のShelf EditorでnToolsのみを削除・保存し、再起動してからRepair Shelf。既存のシェルフファイルが残っている場合は安全のため中止する。
- **Add Help Button**：旧5・6ボタンの既知の構成だけにHelpを追加。Help → Uninstall → Updateの順にし、ツールボタンや他のシェルフは変更しない。既存タブは再構築しない。更新後の再起動を済ませて実行。
- **Add Uninstall Button**：v1.0.1の既存5ボタンシェルフに、明示的な確認後、Uninstallを追加する。Updateを右端に維持。既存タブを再構築せず、既知の構成と一致しない場合は中止する。更新後はMayaを再起動してから実行する。
- **Uninstall**：安全のため自動でシェルフを削除しません。ボタンを押すと、Maya標準のShelf EditorでnToolsタブだけを削除し、Save All Shelvesで保存・再起動する手順を案内します。案内ウィンドウには本体削除用のPythonコードを独立した欄で表示し、右側の「コピー」でコードだけをコピーできます。再起動前にメモ帳などへ保存し、再起動後にScript EditorのPythonタブへ貼り付けて実行してください（管理画面のUninstall選択は不要）。登録情報とシェルフファイルが残っていないことを確認し、最終確認後に本体をバックアップに移動します。他のシェルフやプロジェクトは変更しません。

Updateは本体のみ更新します。Uninstallは2段階の案内方式です。

初回導入で既存の本体がない場合は再起動不要です。既存本体の更新・アンインストール後は、旧モジュールが残るため再起動が必要です。

本体削除用コード（案内ウィンドウのコピー内容）：

```python
import sys, maya.cmds as cmds
p = cmds.internalVar(userScriptDir=True)
if p not in sys.path: sys.path.insert(0,p)
from ntools import installer as nt
nt.uninstall()
```



## v1.0.4からの移行

Updateで本体を更新し、Mayaを再起動します。上記管理コードで **Add Help Button** を選択してください。旧版のUpdateはシェルフ変更の通知を表示しない場合がありますが、ボタン追加はこの明示操作で行います。新規導入では7ボタンを自動登録。

## v1.0.1からの移行

旧Updateを使わず、新版install.pyでFiles Onlyを実行し、Mayaを再起動する。その後、上記管理コードから **Add Uninstall Button** を選択する。通常のアップデートではシェルフを変更しないため、ボタン追加は明示的に行う。既存の5ボタンに変更を加えている場合は安全のため自動追加しない。

## 動画・実機撮影

各ツールのマニュアル内に4ステップの操作図、GIF、MP4があります。Material CreatorはFabのQuixel Megascans Stone Surfaceを題材にしています。実際の素材を使うデモスクリプト、実機撮影とYouTube公開の手順は [撮影・実機検証ガイド](docs/capture_guide.md) を参照。素材本体は含みません。

## 利用時の注意

- File → Set Project を行ってからアセットやマテリアルを読み込む。
- SketchfabのAPIトークンは各自取得し、公開リポジトリに保存しない。モデルごとのライセンス・作者表示を確認。アニメーションやスキンは未対応。
- Poly Haven・Material CreatorはArnold / OpenPBRが必要。アセットの種類によってFBX等のプラグインが必要。
- 四足リグはMotionMaker/HumanIK認定リグではない。転送は試験的機能。必ずシーンのコピーで試す。
- Updateはインターネット接続が必要。学内プロキシ等で失敗した場合は新ZIPから手動導入する。

## 安全性と復旧

v1.0.5は通常更新でシェルフを再構築せず、Maya.env、userSetup、メニューセット、ワークスペース、他のシェルフを直接編集しない。シェルフ登録・削除の直前にメニュー状態を確認し、関連する設定ファイル（存在するもの）をコピーして保存する。Mayaの標準処理による設定変更はあり得る。

本体はMayaのユーザースクリプトディレクトリ内の `ntools` に保存。バックアップは同じ親フォルダ内の `.ntools-backup-*`、`.ntools-uninstalled-*`、`.ntools-ui-backups`。バックアップを自動で削除しない。シェルフ登録失敗時は本体を保持し、UIを自動削除・全設定復元しない。

UIがおかしくなった場合は操作を中止し、Mayaの再起動・標準のメニューセット復元を試す。設定をリセットする場合は、Mayaを終了してから設定フォルダを削除ではなく名前変更してバックアップする。詳しくは [管理者向けガイド](docs/maintainer.md)。

公開コードを信頼できることを確認してからインストールしてください。SHA-256は配布内の整合性検証であり、署名による作者認証ではありません。

## v1.0.0〜1.0.2の起動エラー復旧（重要）

旧版では `saveShelf` に `.mel` 付きのパスを渡していたため、二重拡張子のシェルフができる可能性があります。`nTools.mel` タブや `Object 'nTools.mel' not found` が出る場合は、旧版を再実行しないでください。

1. Mayaを終了し、2027の設定フォルダをバックアップ。
2. `prefs/shelves` 内のnTools関連ファイル（`shelf_nTools.mel`、`shelf_nTools.mel.mel`、`.deleted` 等）を設定フォルダ外へ移動。他のシェルフは移動しない。
3. `prefs/userPrefs.mel` を設定フォルダ外へ退避して再起動。必要なら `prefs` 全体を名前変更して初期化。設定が一部初期化されるのでバックアップを保持。Maya.envは削除不要。
4. UIが正常に戻った後、v1.0.5の `install.py` からFiles Onlyで導入し、再起動。その後Repair Shelfを実行し、再起動して検証。旧版のUpdateは使わない。

新版は拡張子なしのパスを `saveShelf` に渡し、期待したファイルの存在と異常なシェルフ名を検査します。実際のMaya 2027.2での確認が完了するまでは学生に配布しないでください。
