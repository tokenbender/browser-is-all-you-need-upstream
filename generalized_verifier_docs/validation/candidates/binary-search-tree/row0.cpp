#include "binary_search_tree.h"

namespace binary_search_tree {

BinarySearchTree::BinarySearchTree() : root_(nullptr) {}

BinarySearchTree::~BinarySearchTree() {
    _destroy(root_);
}

void BinarySearchTree::insert(int data) {
    _insert(root_, data);
}

bool BinarySearchTree::search(int data) {
    return _search(root_, data);
}

void BinarySearchTree::_insert(Node* node, int data) {
    if (node == nullptr) {
        root_ = new Node{data, nullptr, nullptr};
        return;
    }

    if (data <= node->data) {
        if (node->left == nullptr) {
            node->left = new Node{data, nullptr, nullptr};
        } else {
            _insert(node->left, data);
        }
    } else {
        if (node->right == nullptr) {
            node->right = new Node{data, nullptr, nullptr};
        } else {
            _insert(node->right, data);
        }
    }
}

bool BinarySearchTree::_search(Node* node, int data) {
    if (node == nullptr) {
        return false;
    }

    if (node->data == data) {
        return true;
    }

    if (data <= node->data) {
        return _search(node->left, data);
    } else {
        return _search(node->right, data);
    }
}

void BinarySearchTree::_destroy(Node* node) {
    if (node == nullptr) {
        return;
    }
    _destroy(node->left);
    _destroy(node->right);
    delete node;
}

}  // namespace binary_search_tree
