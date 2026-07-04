# Smoke check for the Blue server refactor.
# Run against a freshly restarted server on localhost:5000 (localhost is auth-exempt).
# Usage: powershell -File scripts\smoke.ps1 [-BaselineFile scripts\smoke_baseline.txt]
param(
    [string]$BaselineFile = ""
)

$base = "http://127.0.0.1:5000"

Write-Host "== Status codes =="
# expected status per URL, from the pre-refactor baseline (2026-07-04):
# /memory/stats was already 503 before the refactor started.
$urls = [ordered]@{
    "/" = 200; "/health" = 200; "/stats" = 200; "/calendar" = 200
    "/contacts/list" = 200; "/visual/list" = 200; "/heads" = 200
    "/documents" = 200; "/chat" = 200; "/duet" = 200; "/perspective" = 200
    "/login" = 200; "/memory/stats" = 503; "/api/rag/stats" = 200
}
$fail = 0
foreach ($u in $urls.Keys) {
    $code = & curl.exe -s -o NUL -w "%{http_code}" "$base$u"
    $mark = if ([int]$code -eq $urls[$u]) { "OK " } else { $fail++; "FAIL" }
    Write-Host ("{0} {1,4} {2}" -f $mark, $code, $u)
}

Write-Host "`n== Static payload hashes =="
$staticUrls = "/assets/blue.css", "/assets/blue.js", "/js/ohbot-heads.js",
              "/calendar", "/contacts", "/visual"
$lines = @()
foreach ($u in $staticUrls) {
    $tmp = Join-Path $env:TEMP "smoke_payload.bin"
    & curl.exe -s -o $tmp "$base$u"
    $hash = (Get-FileHash $tmp -Algorithm SHA256).Hash.Substring(0, 16)
    $lines += "$hash  $u"
    Write-Host "$hash  $u"
}

if ($BaselineFile -and (Test-Path $BaselineFile)) {
    Write-Host "`n== Baseline comparison =="
    $baseline = Get-Content $BaselineFile
    $diff = Compare-Object $baseline $lines
    if ($diff) { $fail++; $diff | Format-Table; Write-Host "HASH MISMATCH vs baseline" }
    else { Write-Host "All static hashes match baseline." }
}

if ($fail -gt 0) { Write-Host "`nSMOKE: FAIL ($fail problem(s))"; exit 1 }
Write-Host "`nSMOKE: PASS"
exit 0
