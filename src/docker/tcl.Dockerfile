FROM debian:bullseye-slim

# Install Tcl and tcllib
RUN apt-get update && apt-get install -y \
    tcl \
    tcllib \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Clone the tcl-lsp repo
RUN git clone https://github.com/0xNatgan/tcl-lsp.git .

# Make the script executable
RUN chmod +x ./tcl-lsp.tcl

# Configure environment for better I/O handling
ENV TCLLIBPATH=/usr/share/tcltk/tcllib1.20

# Set working directory to /workspace (where files will be mounted)
WORKDIR /workspace

# Copy the LSP script to a location accessible from /workspace
RUN cp /app/tcl-lsp.tcl /usr/local/bin/tcl-lsp.tcl && \
    chmod +x /usr/local/bin/tcl-lsp.tcl

EXPOSE 8080
CMD ["tclsh", "/usr/local/bin/tcl-lsp.tcl", "--tcp", "8080"]