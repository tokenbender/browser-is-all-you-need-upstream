#include "binary_search_tree.h"
#include <iostream>

namespace binary_search_tree {

BinarySearchTree::BinarySearchTree() : root(nullptr) {}

BinarySearchTree::~BinarySearchTree() = default;

void BinarySearchTree::_insert(std::shared_ptr<Node> node, int data) {
    if (!node) {
        root = std::make_shared<Node>(Node{data, nullptr, nullptr});
        return;
    }

    if (data < node->data) {
        if (!node->left) {
            node->left = std::make_shared<Node>(Node{data, nullptr, nullptr});
        } else {
            _insert(node->left, data);
        }
    } else {
        if (!node->right) {
            node->right = std::make_shared<Node>(Node{data, nullptr, nullptr});
        } else {
            _insert(node->right, data);
        }
    }
}

bool BinarySearchTree::_search(std::shared_ptr<Node> node, int data) {
    if (!node) {
        return false;
    }

    if (node->data == data) {
        return true;
    }

    if (data < node->data) {
        return _search(node->left, data);
    } else {
        return _search(node->right, data);
    }
}

void BinarySearchTree::insert(int data) {
    _insert(root, data);
}

bool BinarySearchTree::search(int data) {
    return _search(root, data);
}

}  // namespace binary_search_tree
