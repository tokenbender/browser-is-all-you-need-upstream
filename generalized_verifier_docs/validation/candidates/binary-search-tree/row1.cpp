#include "binary_search_tree.h"

namespace binary_search_tree {

BinarySearchTree::BinarySearchTree() : root_(nullptr) {}

void BinarySearchTree::insert(int data) {
    insert(root_, data);
}

void BinarySearchTree::insert(Node*& node, int data) {
    if (node == nullptr) {
        node = new Node{data, nullptr, nullptr};
    } else if (data <= node->data) {
        insert(node->left, data);
    } else {
        insert(node->right, data);
    }
}

bool BinarySearchTree::contains(int data) const {
    return contains(root_, data);
}

bool BinarySearchTree::contains(Node* node, int data) const {
    if (node == nullptr) {
        return false;
    }
    if (data == node->data) {
        return true;
    }
    if (data < node->data) {
        return contains(node->left, data);
    } else {
        return contains(node->right, data);
    }
}

}  // namespace binary_search_tree
