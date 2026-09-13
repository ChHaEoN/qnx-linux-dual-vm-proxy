/* SPDX-License-Identifier: MIT
 *
 * efi-min.h - the minimum of UEFI that M5LOAD.EFI uses.
 *
 * Phase 3b, results/orin-native-port/20260909T1100Z/m5-design.md §4.2: "only the
 * UEFI types and table offsets actually used, written from the specification".
 * Nothing here is copied from edk2 or from any vendor header; every layout below
 * is transcribed from UEFI 2.10 (tables 4-1, 4-6, 4-7, 7-2 and 7-6) and from the
 * AArch64 binding, which makes the calling convention plain AAPCS64. That is what
 * ntoaarch64-gcc emits already, so no __attribute__((ms_abi)) is needed.
 *
 * Only the calls the loader makes are declared: AllocatePages, FreePages,
 * GetMemoryMap, AllocatePool, FreePool, CalculateCrc32, ExitBootServices, and
 * ConOut->OutputString. Every other boot-services slot is a void pointer, so a
 * wrong offset cannot silently become a wrong call.
 */

#ifndef M5_EFI_MIN_H
#define M5_EFI_MIN_H

typedef unsigned char       UINT8;
typedef unsigned short      CHAR16;
typedef unsigned short      UINT16;
typedef unsigned int        UINT32;
typedef unsigned long long  UINT64;
typedef long long           INTN;
typedef unsigned long long  UINTN;
typedef void               *EFI_HANDLE;
typedef UINTN               EFI_STATUS;
typedef UINT64              EFI_PHYSICAL_ADDRESS;
typedef UINT64              EFI_VIRTUAL_ADDRESS;

#define EFI_SUCCESS             0u
#define EFI_LOAD_ERROR          (0x8000000000000000ull | 1u)
#define EFI_INVALID_PARAMETER   (0x8000000000000000ull | 2u)
#define EFI_UNSUPPORTED         (0x8000000000000000ull | 3u)
#define EFI_BUFFER_TOO_SMALL    (0x8000000000000000ull | 5u)
#define EFI_NOT_FOUND           (0x8000000000000000ull | 14u)

#define EFI_ERROR(s)            (((EFI_STATUS)(s)) >> 63)

/* UEFI 2.10 appendix A: Data1, Data2 and Data3 are integers, not byte arrays.
 * Declaring them as bytes is how the first working T0b run came to look up
 * GUIDs that do not exist: the loader printed self=0+0 and then REFUSE fdt,
 * because HandleProtocol and the configuration-table search both matched
 * nothing. */
typedef struct {
	UINT32 Data1;
	UINT16 Data2;
	UINT16 Data3;
	UINT8  Data4[8];
} EFI_GUID;

/* UEFI 2.10 table 4-1: EFI_TABLE_HEADER. */
typedef struct {
	UINT64 Signature;
	UINT32 Revision;
	UINT32 HeaderSize;
	UINT32 CRC32;
	UINT32 Reserved;
} EFI_TABLE_HEADER;

/* UEFI 2.10 table 7-6: EFI_MEMORY_TYPE, only the names the map rules use. */
#define EfiReservedMemoryType       0u
#define EfiLoaderCode               1u
#define EfiLoaderData               2u
#define EfiBootServicesCode         3u
#define EfiBootServicesData         4u
#define EfiRuntimeServicesCode      5u
#define EfiRuntimeServicesData      6u
#define EfiConventionalMemory       7u
#define EfiUnusableMemory           8u
#define EfiACPIReclaimMemory        9u
#define EfiACPIMemoryNVS            10u
#define EfiMemoryMappedIO           11u
#define EfiMemoryMappedIOPortSpace  12u
#define EfiPalCode                  13u
#define EfiPersistentMemory        14u
#define EFI_MAX_MEMORY_TYPE        16u

/* UEFI 2.10 table 7-7: EFI_MEMORY_DESCRIPTOR. Never index an array of these by
 * sizeof(): the map's DescriptorSize is authoritative and may be larger. */
typedef struct {
	UINT32               Type;
	UINT32               Pad;
	EFI_PHYSICAL_ADDRESS PhysicalStart;
	EFI_VIRTUAL_ADDRESS  VirtualStart;
	UINT64               NumberOfPages;
	UINT64               Attribute;
} EFI_MEMORY_DESCRIPTOR;

/* UEFI 2.10 section 7.2: EFI_ALLOCATE_TYPE. */
#define AllocateAnyPages    0u
#define AllocateMaxAddress  1u
#define AllocateAddress     2u

/* UEFI 2.10 table 4-6: EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL. Only OutputString is
 * called; Reset is declared because it precedes it. */
typedef struct EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL {
	EFI_STATUS (*Reset)(struct EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *This, unsigned char ExtendedVerification);
	EFI_STATUS (*OutputString)(struct EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *This, CHAR16 *String);
	void *TestString;
	void *QueryMode;
	void *SetMode;
	void *SetAttribute;
	void *ClearScreen;
	void *SetCursorPosition;
	void *EnableCursor;
	void *Mode;
} EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL;

/* UEFI 2.10 table 4-7: EFI_BOOT_SERVICES, in specification order. Slots the
 * loader does not call are void pointers so that a mistake cannot type-check. */
typedef struct {
	EFI_TABLE_HEADER Hdr;

	/* Task priority */
	void *RaiseTPL;
	void *RestoreTPL;

	/* Memory */
	EFI_STATUS (*AllocatePages)(UINTN Type, UINTN MemoryType, UINTN Pages, EFI_PHYSICAL_ADDRESS *Memory);
	EFI_STATUS (*FreePages)(EFI_PHYSICAL_ADDRESS Memory, UINTN Pages);
	EFI_STATUS (*GetMemoryMap)(UINTN *MemoryMapSize, EFI_MEMORY_DESCRIPTOR *MemoryMap, UINTN *MapKey,
	                           UINTN *DescriptorSize, UINT32 *DescriptorVersion);
	EFI_STATUS (*AllocatePool)(UINTN PoolType, UINTN Size, void **Buffer);
	EFI_STATUS (*FreePool)(void *Buffer);

	/* Event and timer */
	void *CreateEvent;
	void *SetTimer;
	void *WaitForEvent;
	void *SignalEvent;
	void *CloseEvent;
	void *CheckEvent;

	/* Protocol handler */
	void *InstallProtocolInterface;
	void *ReinstallProtocolInterface;
	void *UninstallProtocolInterface;
	EFI_STATUS (*HandleProtocol)(EFI_HANDLE Handle, EFI_GUID *Protocol, void **Interface);
	void *Reserved;
	void *RegisterProtocolNotify;
	void *LocateHandle;
	void *LocateDevicePath;
	void *InstallConfigurationTable;

	/* Image */
	void *LoadImage;
	void *StartImage;
	void *Exit;
	void *UnloadImage;
	EFI_STATUS (*ExitBootServices)(EFI_HANDLE ImageHandle, UINTN MapKey);

	/* Miscellaneous */
	void *GetNextMonotonicCount;
	void *Stall;
	void *SetWatchdogTimer;          /* never called: §7.4 */

	/* DriverSupport */
	void *ConnectController;
	void *DisconnectController;

	/* Open and close protocol */
	EFI_STATUS (*OpenProtocol)(EFI_HANDLE Handle, EFI_GUID *Protocol, void **Interface,
	                           EFI_HANDLE AgentHandle, EFI_HANDLE ControllerHandle, UINT32 Attributes);
	void *CloseProtocol;
	void *OpenProtocolInformation;

	/* Library */
	void *ProtocolsPerHandle;
	void *LocateHandleBuffer;
	void *LocateProtocol;
	void *InstallMultipleProtocolInterfaces;
	void *UninstallMultipleProtocolInterfaces;

	/* 32-bit CRC */
	EFI_STATUS (*CalculateCrc32)(void *Data, UINTN DataSize, UINT32 *Crc32);

	/* Miscellaneous, continued */
	void *CopyMem;
	void *SetMem;
	void *CreateEventEx;
} EFI_BOOT_SERVICES;

/* UEFI 2.10 table 4-5: EFI_CONFIGURATION_TABLE. */
typedef struct {
	EFI_GUID VendorGuid;
	void    *VendorTable;
} EFI_CONFIGURATION_TABLE;

/* UEFI 2.10 table 4-3: EFI_SYSTEM_TABLE. */
typedef struct {
	EFI_TABLE_HEADER Hdr;
	CHAR16          *FirmwareVendor;
	UINT32           FirmwareRevision;
	EFI_HANDLE       ConsoleInHandle;
	void            *ConIn;
	EFI_HANDLE       ConsoleOutHandle;
	EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *ConOut;
	EFI_HANDLE       StandardErrorHandle;
	void            *StdErr;
	void            *RuntimeServices;
	EFI_BOOT_SERVICES *BootServices;
	UINTN            NumberOfTableEntries;
	EFI_CONFIGURATION_TABLE *ConfigurationTable;
} EFI_SYSTEM_TABLE;

/* UEFI 2.10 section 9.1: EFI_LOADED_IMAGE_PROTOCOL, truncated after the fields
 * the loader reads (LoadOptions for check/go, ImageBase and ImageSize for the
 * start token). 5b1b31a1-9562-11d2-8e3f-00a0c969723b. */
typedef struct {
	UINT32      Revision;
	EFI_HANDLE  ParentHandle;
	void       *SystemTable;
	EFI_HANDLE  DeviceHandle;
	void       *FilePath;
	void       *Reserved;
	UINT32      LoadOptionsSize;
	void       *LoadOptions;
	void       *ImageBase;
	UINT64      ImageSize;
	UINTN       ImageCodeType;
	UINTN       ImageDataType;
	void       *Unload;
} EFI_LOADED_IMAGE_PROTOCOL;

#define EFI_LOADED_IMAGE_PROTOCOL_GUID \
	{ 0x5b1b31a1, 0x9562, 0x11d2, { 0x8e, 0x3f, 0x00, 0xa0, 0xc9, 0x69, 0x72, 0x3b } }

/* The device-tree configuration table, b1b621d5-f19c-41a5-830b-d9152c69aae0
 * (m5-design.md §3.3 step 2). Not a UEFI specification GUID: it is the
 * EFI_DTB_TABLE_GUID that edk2 and the ARM boot conventions publish. */
#define EFI_DTB_TABLE_GUID \
	{ 0xb1b621d5, 0xf19c, 0x41a5, { 0x83, 0x0b, 0xd9, 0x15, 0x2c, 0x69, 0xaa, 0xe0 } }

/* OpenProtocol attribute: BY_HANDLE_PROTOCOL, the read-only form used for
 * LOADED_IMAGE. HandleProtocol is equivalent and simpler; both are declared so
 * the implementation can pick the one the firmware likes. */
#define EFI_OPEN_PROTOCOL_GET_PROTOCOL 0x00000002u

#endif /* M5_EFI_MIN_H */
