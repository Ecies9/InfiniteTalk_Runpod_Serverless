Param(
    [string]$Tag = $env:TAG
        ? $env:TAG
        : "infinitetalk-runpod:gpu",
    [string]$Dockerfile = "InfiniteTalk_Runpod_Serverless/Dockerfile",
    [int]$PrefetchModels = $(If ($env:PREFETCH_MODELS) { [int]$env:PREFETCH_MODELS } Else { 0 })
)

Write-Host "Building image: $Tag"
docker build `
  -t $Tag `
  -f $Dockerfile `
  --build-arg PREFETCH_MODELS=$PrefetchModels `
  .

if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed."
    exit $LASTEXITCODE
}

Write-Host "Built $Tag"