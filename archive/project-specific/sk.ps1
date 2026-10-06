# sk.ps1 —— 调用 DSH <-> SketchUp 桥客户端（自动用工作区里那个 Python）
#
# 用法：
#   .\sk.ps1 ping
#   .\sk.ps1 info
#   .\sk.ps1 ruby "puts Sketchup.version"
#   .\sk.ps1 ruby 'ents = Sketchup.active_model.entities; puts ents.length' -Values
#   .\sk.ps1 shot --name look1
#   .\sk.ps1 reload
#   .\sk.ps1 undo 1
#   .\sk.ps1            # 不带参数 = 交互式 shell
#
# 说明：这个脚本让 DSH 在会话里调用时不必每次写全 Python 路径。

$ErrorActionPreference = 'Stop'
$py  = 'C:\Users\asus\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$cli = Join-Path $PSScriptRoot 'sk_client.py'

if (-not (Test-Path $py))  { throw "找不到 Python: $py" }
if (-not (Test-Path $cli)) { throw "找不到客户端: $cli" }

$env:PYTHONIOENCODING = 'utf-8'

if ($args.Count -eq 0) {
    & $py $cli shell
} else {
    & $py $cli @args
}
exit $LASTEXITCODE
