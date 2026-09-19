"""
Retrain the plate-character classifier (image_classifier.py's FCModel)
on the character crops produced by scripts/convert_char_annotations.py.

This is a tiny MLP on 28x28 grayscale images, so it trains fast even on
CPU. Saves:
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
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from image_classifier import FCModel  # noqa: E402

DATA_DIR = REPO_ROOT / "data" / "IR-LPR" / "car-image"
MODELS_DIR = REPO_ROOT / "models"

TRANSFORM = transforms.Compose([
    transforms.Grayscale(),
    transforms.Resize((28, 28)),
    transforms.ToTensor(),
])


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

    train_dataset = datasets.ImageFolder(root=str(train_dir), transform=TRANSFORM)
    val_dataset = datasets.ImageFolder(root=str(val_dir), transform=TRANSFORM)
    if train_dataset.classes != val_dataset.classes:
        raise SystemExit(
            f"train/val class sets differ: "
            f"{set(train_dataset.classes) ^ set(val_dataset.classes)}"
        )
    print(f"{len(train_dataset.classes)} classes: {train_dataset.classes}")
    print(f"{len(train_dataset)} train images, {len(val_dataset)} val images")

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on {device}")
    model = FCModel(len(train_dataset.classes)).to(device)
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
    classes_path.write_text(json.dumps(train_dataset.classes, ensure_ascii=False, indent=2))
    print(f"Saved {weights_path} and {classes_path}")


if __name__ == "__main__":
    main()
