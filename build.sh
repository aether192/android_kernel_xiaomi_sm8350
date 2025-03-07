#!/usr/bin/env bash
# Build Script for MigoKernel
# Copyright (C) 2022-2023 Mar Yvan D.

# Dependency preparation
sudo apt install bc -y
sudo apt-get install device-tree-compiler -y

# Main Variables
KDIR=$(pwd)
DATE=$(date +%d-%h-%Y-%R:%S | sed "s/:/./g")
START=$(date +"%s")
TCDIR=$(pwd)/clang
DTB=out/arch/arm64/boot/dtb
DTBO=out/arch/arm64/boot/dtbo.img
IMAGE=out/arch/arm64/boot/Image.gz-dtb

# Naming Variables
KNAME="MigoKernel"
VERSION="v1.0"
CODENAME="renoir"
MIN_HEAD=$(git rev-parse HEAD)
export KVERSION="${KNAME}-${VERSION}-${CODENAME}-$(echo ${MIN_HEAD:0:8})"

# Build Information
LINKER=ld.lld
export COMPILER_NAME="$(${TCDIR}/bin/clang --version | head -n 1 | perl -pe 's/\(http.*?\)//gs' | sed -e 's/  */ /g' -e 's/[[:space:]]*$//')"
export LINKER_NAME="$("${TCDIR}"/bin/${LINKER} --version | head -n 1 | sed 's/(compatible with [^)]*)//' | head -n 1 | perl -pe 's/\(http.*?\)//gs' | sed -e 's/  */ /g' -e 's/[[:space:]]*$//')"
export KBUILD_BUILD_USER=migolxlr
export KBUILD_BUILD_HOST=runner
export DEVICE="Mi 11 Lite 5G"
export CODENAME="renoir"
export TYPE="Stable"
export DISTRO=$(source /etc/os-release && echo "${NAME}")

# Telegram Integration Variables
CHAT_ID=""
PUBCHAT_ID=""
BOT_ID=""

function publicinfo() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_ID}/sendMessage" \
        -d chat_id="$PUBCHAT_ID" \
        -d "disable_web_page_preview=true" \
        -d "parse_mode=html" \
        -d text="<b>Automated build started for ${DEVICE} (${CODENAME})</b>"
}
function sendinfo() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_ID}/sendMessage" \
        -d chat_id="$CHAT_ID" \
        -d "disable_web_page_preview=true" \
        -d "parse_mode=html" \
        -d text="<b>Laboratory Machine: Build Triggered</b>%0A<b>Docker: </b><code>$DISTRO</code>%0A<b>Build Date: </b><code>${DATE}</code>%0A<b>Device: </b><code>${DEVICE} (${CODENAME})</code>%0A<b>Kernel Version: </b><code>$(make kernelversion 2>/dev/null)</code>%0A<b>Build Type: </b><code>${TYPE}</code>%0A<b>Compiler: </b><code>${COMPILER_NAME}</code>%0A<b>Linker: </b><code>${LINKER_NAME}</code>%0A<b>Zip Name: </b><code>${KVERSION}</code>%0A<b>Branch: </b><code>$(git rev-parse --abbrev-ref HEAD)</code>%0A<b>Last Commit Details: </b><a href='${REPO_URL}/commit/${COMMIT_HASH}'>${COMMIT_HASH}</a> <code>($(git log --pretty=format:'%s' -1))</code>"
}
function push() {
    cd AnyKernel3
    ZIP=$(echo *.zip)
    curl -F document=@$ZIP "https://api.telegram.org/bot${BOT_ID}/sendDocument" \
        -F chat_id="$CHAT_ID" \
        -F "disable_web_page_preview=true" \
        -F "parse_mode=html" \
        -F caption="Build took $(($DIFF / 60)) minutes and $(($DIFF % 60)) seconds. | <b>Compiled with: ${COMPILER_NAME} + ${LINKER_NAME}.</b>"
}
function finerr() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_ID}/sendMessage" \
        -d chat_id="$CHAT_ID" \
        -d "disable_web_page_preview=true" \
        -d "parse_mode=html" \
        -d text="Compilation failed, please check build logs for errors."
    exit 1
}
function compile() {
    make O=out ARCH=arm64 vendor/lahaina-qgki_defconfig vendor/debugfs.config vendor/xiaomi_QGKI.config vendor/renoir_QGKI.config
    export PATH=${TCDIR}/bin/:/usr/bin/:${PATH}
    export CROSS_COMPILE=aarch64-linux-gnu-
    export CROSS_COMPILE_ARM32=arm-linux-gnueabi-
    export LLVM=1
    export LLVM_IAS=1
    make -j$(nproc --all) O=out ARCH=arm64 CC=clang LD=ld.lld AR=llvm-ar AS=llvm-as NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip 
    
    kernel="out/arch/arm64/boot/Image.gz-dtb"
    dtb="out/arch/arm64/boot/dts/vendor/qcom/shima.dtb"
    dtbo="out/arch/arm64/boot/dts/vendor/qcom/renoir-sm7350-overlay.dtbo"

    if ! [ -a "$IMAGE" ] || [ -a "$DTB" ] || [ -a "$DTBO" ] ; then
        finerr
        exit 1
    fi
}
echo -e "\nKernel compiled succesfully! Zipping up...\n"
if [ -d "$AK3_DIR" ]; then
	cp -r $AK3_DIR AnyKernel3
	git -C AnyKernel3 checkout master &> /dev/null
elif ! git clone -q https://github.com/aether192/AnyKernel3 -b master; then
	echo -e "\nAnyKernel3 repo not found locally and couldn't clone from GitHub! Aborting..."
	exit 1
fi
cp $kernel AnyKernel3
cp $dtb AnyKernel3/dtb
python2 scripts/dtc/libfdt/mkdtboimg.py create AnyKernel3/dtbo.img --page_size=4096 $dtbo
cp $(find out/modules/lib/modules/5.4* -name '*.ko') AnyKernel3/modules/vendor/lib/modules/
cp out/modules/lib/modules/5.4*/modules.{alias,dep,softdep} AnyKernel3/modules/vendor/lib/modules
cp out/modules/lib/modules/5.4*/modules.order AnyKernel3/modules/vendor/lib/modules/modules.load
sed -i 's/\(kernel\/[^: ]*\/\)\([^: ]*\.ko\)/\/vendor\/lib\/modules\/\2/g' AnyKernel3/modules/vendor/lib/modules/modules.dep
sed -i 's/.*\///g' AnyKernel3/modules/vendor/lib/modules/modules.load
rm -rf out/arch/arm64/boot out/modules
cd AnyKernel3
zip -r9 "../$ZIPNAME" * -x .git README.md *placeholder
cd ..
rm -rf AnyKernel3
echo -e "\nCompleted in $((SECONDS / 60)) minute(s) and $((SECONDS % 60)) second(s) !"
echo "Zip: $ZIPNAME"

publicinfo
sendinfo
compile
END=$(date +"%s")
DIFF=$(($END - $START))
push
