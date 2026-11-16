# nTools v1.0.1

Maya向け授業用ツールセット。Windows / macOS、Maya 2027（Arnold / OpenPBR利用環境）を想定。実機での動作確認は配布前に行ってください。

![nTools shelf preview](docs/shelf_preview.png)

| ツール | バージョン | 機能 |
|---|---|---|
| Sketchfab Asset Browser | 1.2 | 静的glTFモデルの検索・インポート、OpenPBR |
| PolyHaven Asset Browser | 5.2 | モデル・テクスチャ・HDRI、ローカルライブラリ |
| Material Creator | 1.3 | ローカルテクスチャ / JSONからOpenPBR作成 |
| Quadruped Quick Rig | 2.4.0 | 四足ガイド、IK/FK、試験的なリターゲット |

## 初回導入（学生）

1. [GitHub](https://github.com/nmasaaki-web/nTools) の Code → Download ZIP を選択し、展開する。
2. Mayaを起動し、Fileメニュー・メニューセット・シェルフが正常に表示されていることを確認。作業中のシーンを保存する。
3. 展開した `install.py` をMayaのビューポートへドラッグ＆ドロップ。確認画面で **Install + Shelf** を選ぶと、未登録の場合に限りnToolsシェルフを作成する。**Files Only** は本体だけを導入する（安全確認用、初期選択）。
4. Mayaを再起動。nToolsタブの4ツールと右端Updateを確認する。

ドラッグできない場合はScript Editorの **Python** タブで実行し、展開した `install.py` を選択：

```python
import maya.cmds as cmds
import runpy
p = cmds.fileDialog2(fileMode=1, fileFilter='Python (*.py)', caption='Select nTools install.py') or []
if p:
    runpy.run_path(p[0], run_name='__main__')
```

## 旧版 v1.0.0 からの移行（重要）

旧版のUpdateはシェルフを再登録するため、**旧版のUpdateを押さず**、v1.0.1のZIPをダウンロードして上記のインストールを行う。まずFiles Onlyを選択し、Mayaを再起動してUIが正常か確認することを推奨。既存のnToolsシェルフは変更しない。タブがない場合は次のRepair Shelfを実行する。

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
- **Uninstall**：既存nToolsシェルフが管理対象のボタンのみで構成されていることを確認し、Maya公式の削除確認を表示。削除が確認できた場合のみ本体をバックアップに移動する。他のボタンが混在する場合やMELファイルが残る場合は中止。Mayaを再起動する。

Updateボタンはこれまでどおり直接更新を行う。管理メニューは上記コードで開く。ファイルのみ導入した場合にも使える。

## 利用時の注意

- File → Set Project を行ってからアセットやマテリアルを読み込む。
- SketchfabのAPIトークンは各自取得し、公開リポジトリに保存しない。モデルごとのライセンス・作者表示を確認。アニメーションやスキンは未対応。
- Poly Haven・Material CreatorはArnold / OpenPBRが必要。アセットの種類によってFBX等のプラグインが必要。
- 四足リグはMotionMaker/HumanIK認定リグではない。転送は試験的機能。必ずシーンのコピーで試す。
- Updateはインターネット接続が必要。学内プロキシ等で失敗した場合は新ZIPから手動導入する。

## 安全性と復旧

v1.0.1は通常更新でシェルフを再構築せず、Maya.env、userSetup、メニューセット、ワークスペース、他のシェルフを直接編集しない。シェルフ登録・削除の直前にメニュー状態を確認し、関連する設定ファイル（存在するもの）をコピーして保存する。Mayaの標準処理による設定変更はあり得る。

本体はMayaのユーザースクリプトディレクトリ内の `ntools` に保存。バックアップは同じ親フォルダ内の `.ntools-backup-*`、`.ntools-uninstalled-*`、`.ntools-ui-backups`。バックアップを自動で削除しない。シェルフ登録失敗時は本体を保持し、UIを自動削除・全設定復元しない。

UIがおかしくなった場合は操作を中止し、Mayaの再起動・標準のメニューセット復元を試す。設定をリセットする場合は、Mayaを終了してから設定フォルダを削除ではなく名前変更してバックアップする。詳しくは [管理者向けガイド](docs/maintainer.md)。

公開コードを信頼できることを確認してからインストールしてください。SHA-256は配布内の整合性検証であり、署名による作者認証ではありません。
