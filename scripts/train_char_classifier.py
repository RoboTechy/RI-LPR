"""
Retrain the plate-character classifier (image_classifier.py's CharCNN)
on the character crops produced by scripts/convert_char_annotations.py.

A first run with the original FCModel (a flat MLP) plateaued around
91-92% per-character val accuracy - not nearly enough for reliable full
plates, since errors compound across all ~8 characters
(0.915**8 ~= 49% chance of reading an entire plate correctly). Flattening
the image throws away spatial structure a small CNN can use instead, so
this trains CharCNN, plus light rotation/translation augmentation (real
segmented crops from extract_digits() are rarely perfectly centered).
Still tiny - a few hundred K params - so CPU inference stays effectively
free even without a GPU. Saves:
    models/ir_lpr_char_classifier.pt          - state_dict
    models/ir_lpr_char_classifier_classes.json - ordered class list
                                                  (index -> character),
                                                  needed at inference time
                                                  since ImageFolder's
                                                  class order depends on
                                                  whatever folders exist
                                                  on the machine that
                                                  trained it.

Usage:
    python scripts/train_char_classifier.py
    python scripts/train_char_classifier.py --epochs 40
"""

import argparse
import json
import sys
from pathlib import Path

import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from image_classifier import CharCNN  # noqa: E402

DATA_DIR = REPO_ROOT / "data" / "IR-LPR" / "car-image"
MODELS_DIR = REPO_ROOT / "models"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

# Real crops from extract_digits() are rarely perfectly centered/aligned,
# so lightly augment the train split; val stays unaugmented for an honest
# accuracy read.
TRAIN_TRANSFORM = transforms.Compose([
    transforms.Grayscale(),
    transforms.Resize((28, 28)),
    transforms.RandomAffine(degrees=10, translate=(0.1, 0.1)),
    transforms.ToTensor(),
])
VAL_TRANSFORM = transforms.Compose([
    transforms.Grayscale(),
    transforms.Resize((28, 28)),
    transforms.ToTensor(),
])


class CharFolderDataset(Dataset):
    """Like torchvision's ImageFolder, but classes can have zero samples in
    a given split (ImageFolder hard-errors on an empty class folder, which
    real plate-character classes hit - some letters are rare enough that a
    train/val split can leave one side without any examples of them)."""

    def __init__(self, root: Path, classes: list, class_to_idx: dict, transform):
        self.transform = transform
        self.samples = []
        for cls in classes:
            cls_dir = root / cls
            if not cls_dir.is_dir():
                continue
            for path in cls_dir.iterdir():
                if path.suffix.lower() in IMAGE_EXTENSIONS:
                    self.samples.append((path, class_to_idx[cls]))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        image = Image.open(path)
        if self.transform:
            image = self.transform(image)
        return image, label


def evaluate(model, loader, device) -> float:
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            predicted = model(images).argmax(dim=1)
            correct += (predicted == labels).sum().item()
            total += labels.size(0)
    return correct / total if total else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    train_dir = DATA_DIR / "train" / "chars"
    val_dir = DATA_DIR / "val" / "chars"
    if not train_dir.exists() or not val_dir.exists():
        raise SystemExit(
            f"{train_dir} / {val_dir} not found - run "
            f"scripts/convert_char_annotations.py first."
        )

    # Some plate characters are rare enough that a random train/val split can
    # leave a class with zero examples on one side. Build one shared class
    # list (and index mapping) from both splits combined, so train and val
    # always agree on which index means which character - a class missing
    # from train just won't be learned; one missing from val just won't show
    # up in val_acc.
    train_classes = {p.name for p in train_dir.iterdir() if p.is_dir()}
    val_classes = {p.name for p in val_dir.iterdir() if p.is_dir()}
    for missing in sorted(val_classes - train_classes):
        print(f"warning: class {missing!r} has no train images, only val")
    for missing in sorted(train_classes - val_classes):
        print(f"warning: class {missing!r} has no val images, only train")
    classes = sorted(train_classes | val_classes)
    class_to_idx = {cls: i for i, cls in enumerate(classes)}

    train_dataset = CharFolderDataset(train_dir, classes, class_to_idx, TRAIN_TRANSFORM)
    val_dataset = CharFolderDataset(val_dir, classes, class_to_idx, VAL_TRANSFORM)
    print(f"{len(classes)} classes: {classes}")
    print(f"{len(train_dataset)} train images, {len(val_dataset)} val images")

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on {device}")
    model = CharCNN(len(classes)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running_loss += loss.item() * images.size(0)

        train_loss = running_loss / len(train_dataset)
        val_acc = evaluate(model, val_loader, device)
        print(f"epoch {epoch}/{args.epochs}  train_loss={train_loss:.4f}  val_acc={val_acc:.4f}")

    MODELS_DIR.mkdir(exist_ok=True)
    weights_path = MODELS_DIR / "ir_lpr_char_classifier.pt"
    classes_path = MODELS_DIR / "ir_lpr_char_classifier_classes.json"
    torch.save(model.state_dict(), weights_path)
    classes_path.write_text(json.dumps(classes, ensure_ascii=False, indent=2))
    print(f"Saved {weights_path} and {classes_path}")


if __name__ == "__main__":
    main()
