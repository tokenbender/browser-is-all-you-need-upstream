#include "binary_search_tree.h"

namespace binary_search_tree {

BinarySearchTree::BinarySearchTree() : root(nullptr) {}

BinarySearchTree::~BinarySearchTree() {
    Node* current = root;
    while (current != nullptr) {
        if (current->left == nullptr) {
            Node* temp = current;
            current = current->right;
            delete temp;
        } else {
            Node* predecessor = current->left;
            while (predecessor->right != nullptr) {
                predecessor = predecessor->right;
            }
            Node* temp = current;
            current = predecessor->right;
            predecessor->right = current->left;
            current->left = temp;
        }
    }
}

void BinarySearchTree::insert(int data) {
    insert(root, data);
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

bool BinarySearchTree::search(int data) const {
    return search(root, data);
}

bool BinarySearchTree::search(Node* node, int data) const {
    if (node == nullptr) {
        return false;
    } else if (data == node->data) {
        return true;
    } else if (data < node->data) {
        return search(node->left, data);
    } else {
        return search(node->right, data);
    }
}

}  // namespace binary_search_tree
