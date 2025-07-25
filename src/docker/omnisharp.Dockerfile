FROM mcr.microsoft.com/dotnet/sdk:8.0

# Install dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install .NET Framework 4.8 Reference Assemblies via NuGet
# This provides the reference assemblies needed for .NET Framework projects
# Install .NET Framework 4.8 Reference Assemblies for OmniSharp
RUN mkdir -p /usr/share/dotnet/packs/Microsoft.NETFramework.ReferenceAssemblies.net48/1.0.0/ref/net48 \
    && wget -q "https://www.nuget.org/api/v2/package/Microsoft.NETFramework.ReferenceAssemblies.net48/1.0.0" -O /tmp/net48.zip \
    && unzip -q /tmp/net48.zip -d /tmp/net48 \
    && find /tmp/net48 -type d -name net48 | while read dir; do cp -r "$dir/." /usr/share/dotnet/packs/Microsoft.NETFramework.ReferenceAssemblies.net48/1.0.0/ref/net48/; done \
    && rm -rf /tmp/net48 /tmp/net48.zip
# Create app directory
WORKDIR /app

# Download and extract OmniSharp Linux x64 version
RUN curl -L https://github.com/OmniSharp/omnisharp-roslyn/releases/download/v1.39.12/omnisharp-linux-x64-net6.0.tar.gz \
    | tar -xzv -C /app

# Make the OmniSharp binary executable
RUN chmod +x /app/OmniSharp

# Set working directory for projects
WORKDIR /workspace

# Expose port (not strictly necessary for stdin/stdout LSP)
EXPOSE 8088

# Set the command to run OmniSharp in LSP mode
CMD ["/app/OmniSharp", "--languageserver"]
