param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedMode,
    [Parameter(Mandatory = $true)]
    [string]$ExpectedFingerprint
)

$deadline = (Get-Date).AddMinutes(4)
$healthUrl = "$Url/api/v1/health"
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
        if (
            $health.status -eq "ok" -and
            $health.mode -eq $ExpectedMode -and
            $health.build_fingerprint -eq $ExpectedFingerprint
        ) {
            if ($ExpectedMode -eq "private") {
                $bootstrap = Invoke-RestMethod -Uri "$Url/api/v1/app/bootstrap" -TimeoutSec 15
                $datasets = Invoke-RestMethod -Uri "$Url/api/v1/datasets" -TimeoutSec 30
                $business = Invoke-RestMethod -Uri "$Url/api/v1/business/datasets" -TimeoutSec 30
                $datasetId = $bootstrap.data.default_dataset_id
                $catalogIds = @($datasets.data | ForEach-Object { $_.dataset_id })
                $businessIds = @($business.data | ForEach-Object { $_.dataset_id })
                if (
                    -not $datasetId -or
                    $datasetId -notin $catalogIds -or
                    $datasetId -notin $businessIds
                ) {
                    throw "Unified dataset smoke check is not ready"
                }
            }
            Start-Process $Url
            exit 0
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
exit 1
