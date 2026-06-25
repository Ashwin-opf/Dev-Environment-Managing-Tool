# Download rustup-init.exe
Write-Host "Downloading Rust installer..."
Invoke-WebRequest -Uri "https://win.rustup.rs/x86_64" -OutFile "scratch\rustup-init.exe"

# Run the installer silently
Write-Host "Installing Rust and Cargo..."
Start-Process -FilePath "scratch\rustup-init.exe" -ArgumentList "-y" -NoNewWindow -Wait

# Clean up installer
Remove-Item "scratch\rustup-init.exe" -ErrorAction SilentlyContinue

# Verify installation
$cargoPath = "$env:USERPROFILE\.cargo\bin"
if (Test-Path "$cargoPath\cargo.exe") {
    Write-Host "Rust/Cargo successfully installed!"
    $env:PATH += ";$cargoPath"
    cargo --version
} else {
    Write-Error "Rust/Cargo installation failed or not found in default path."
}
