#!/bin/bash

# Detect the operating system
os=$(uname)

# Set the update source folder based on the OS
if [ "$os" = "Darwin" ]; then
    # macOS detected
    executable_name=RimSort.app
    grandparent_dir="$(dirname "$(dirname "$(dirname "$(realpath "$0")")")")"
    update_source_folder="${TMPDIR:-/tmp}"

    # Ensure the application is killed
    if ! killall -q RimSort; then
        echo "Warning: RimSort process not found or could not be killed."
    fi
else
    # Assume Linux if not macOS
    executable_name=RimSort.bin
    parent_dir="$(realpath .)"
    update_source_folder="/tmp/RimSort"

    # Ensure the application is killed
    if ! killall -q "$executable_name"; then
        echo "Warning: $executable_name process not found or could not be killed."
    fi
fi

# Display a message indicating the update operation is starting in 5 seconds
echo "Updating RimSort in 5 seconds. Press any key to cancel."
read -t 5 -n 1 cancel
if [ $? -eq 0 ]; then
    echo "Update cancelled by user."
    exit 1
fi

# Check if update source folder exists
if [ ! -d "$update_source_folder" ]; then
    echo "Update source folder does not exist: $update_source_folder"
    exit 1
fi

# Execute RimSort from the current directory
if [ "$os" = "Darwin" ]; then # macOS detected
    # Remove old installation safely after user confirmation
    if [ -d "${grandparent_dir}" ] && [ -e "${grandparent_dir}/Contents/MacOS/RimSort" ]; then
        echo "RimSort installation directory found at ${grandparent_dir}."
        read -p "Are you sure you want to delete this directory and update? (y/N): " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            echo "Update cancelled by user."
            exit 1
        fi
        if ! rm -rf "${grandparent_dir}"; then
            echo "Failed to remove old installation at ${grandparent_dir}"
            exit 1
        fi
    else
        echo "Safety check failed: ${grandparent_dir} is not a valid RimSort installation directory."
        exit 1
    fi
    # Move files from the update source folder to the current directory
    if ! chmod +x "${update_source_folder}/${executable_name}/Contents/MacOS/RimSort" || ! chmod +x "${update_source_folder}/${executable_name}/Contents/MacOS/todds/todds"; then
        echo "Failed to set executable permissions"
        exit 1
    fi
    if ! mv "${update_source_folder}/${executable_name}" "${grandparent_dir}"; then
        echo "Failed to move update files to ${grandparent_dir}"
        exit 1
    fi
    open "${grandparent_dir}"
else # Assume Linux if not macOS
    # Remove old installation safely after user confirmation
    if [ -d "${parent_dir}" ] && [ -e "${parent_dir}/RimSort.bin" ]; then
        echo "RimSort installation directory found at ${parent_dir}."
        read -p "Are you sure you want to delete this directory and update? (y/N): " confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            echo "Update cancelled by user."
            exit 1
        fi
        if ! rm -rf "${parent_dir}"; then
            echo "Failed to remove old installation at ${parent_dir}"
            exit 1
        fi
    else
        echo "Safety check failed: ${parent_dir} is not a valid RimSort installation directory."
        exit 1
    fi
    # Move files from the update source folder to the current directory
    if ! chmod +x "${update_source_folder}/${executable_name}" || ! chmod +x "${update_source_folder}/todds/todds"; then
        echo "Failed to set executable permissions"
        exit 1
    fi
    if ! mv "${update_source_folder}" "${parent_dir}"; then
        echo "Failed to move update files to ${parent_dir}"
        exit 1
    fi
    cd "${parent_dir}" && ./"$executable_name" &
    cd "${parent_dir}" || { echo "Failed to cd to ${parent_dir}"; exit 1; }
fi
