#!/bin/bash
# ./helper-scripts/ai-collector.sh
# nsys-ai-claude-3.5

# attention - all files in TARGET_DIR will get removed!
# The script recursively searches for files with specific extensions (.md, .py, .yaml, .yml) in a directory tree while respecting 
# .gitignore rules, and copies them to a target directory with flattened filenames where path separators are converted to 
# underscores (e.g., ./path/to/file.py becomes path_to_file.py).


# Set strict error handling
set -euo pipefail

# Define source and target directories
SOURCE_DIR="./libvirt"
TARGET_DIR="./target-ai-working-dir"


# Define file extensions to copy
EXTENSIONS=( "py" "yaml" "yml")

# Create target directory if it doesn't exist
mkdir -p "${TARGET_DIR}"

# clean the Directory if exists and is not empty
if [ "$(ls -A $TARGET_DIR)" ]; then
    echo "Cleaning target directory: ${TARGET_DIR}"
    rm -r ${TARGET_DIR}/*
fi

# Function to check if a path is ignored by git
is_ignored() {
    local path="$1"
    git check-ignore -q "$path" 2>/dev/null
    return $?
}

# Function to flatten path and copy file
copy_with_flat_name() {
    local file="$1"
    local rel_path="${file#./}"
    
    # Convert path separators to underscores and remove leading/trailing underscores
    local flat_name=$(echo "$rel_path" | sed 's/[\/\.]/_/g' | sed 's/^_//g')
    
    # Keep the original extension
    local extension="${file##*.}"
    flat_name="${flat_name%_$extension}.$extension"
    
    local target_file="${TARGET_DIR}/${flat_name}"
    
    # Check if target file already exists
    if [ -f "$target_file" ]; then
        echo "Warning: File with name $flat_name already exists. Skipping: $file"
        return
    fi
    
    cp "$file" "$target_file"
    echo "Copied: $file -> $target_file"
}

# Function to process directory
process_directory() {
    local dir="$1"
    local ext="$2"
    
    # Skip if directory is in .git
    if [[ "$dir" == */.git/* ]]; then
        return
    fi
    
    # Check if directory is ignored (only if .git exists)
    if [ -d ".git" ] && is_ignored "$dir"; then
        echo "Skipping ignored directory: $dir"
        return
    fi
    
    # Process files in this directory
    find "$dir" -maxdepth 1 -type f -name "*.${ext}" -print0 | while IFS= read -r -d '' file; do
        if [ -d ".git" ] && is_ignored "$file"; then
            echo "Skipping ignored file: $file"
            continue
        fi
        copy_with_flat_name "$file"
    done
    
    # Recursively process subdirectories
    find "$dir" -maxdepth 1 -type d ! -path "$dir" -print0 | while IFS= read -r -d '' subdir; do
        process_directory "$subdir" "$ext"
    done
}

# Main processing
echo "Starting file copy process..."

# Initialize git repository if not already initialized
if [ ! -d ".git" ]; then
    echo "Warning: No git repository found. All files will be processed."
fi

# Process each extension starting from the source directory
for ext in "${EXTENSIONS[@]}"; do
    echo "Processing .$ext files..."
    process_directory "$SOURCE_DIR" "$ext"
done

# remove all file names containing __init__ as they are not needed
find $TARGET_DIR -name "*__init__*" -exec rm -f {} \;
echo "File copy process completed!"
