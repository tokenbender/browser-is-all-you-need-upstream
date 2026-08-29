#include "binary_search_tree.h"

namespace binary_search_tree {

template <typename T>
BinarySearchTree<T>::~BinarySearchTree() {
    delete_tree(root_);
}

template <typename T>
void BinarySearchTree<T>::insert(const T& value) {
    insert(root_, value);
}

template <typename T>
bool BinarySearchTree<T>::search(const T& value) const {
    return search(root_, value);
}

template <typename T>
void BinarySearchTree<T>::insert(Node*& node, const T& value) {
    if (node == nullptr) {
        node = new Node(value);
    } else if (value <= node->data) {
        insert(node->left, value);
    } else {
        insert(node->right, value);
    }
}

template <typename T>
bool BinarySearchTree<T>::search(Node* node, const T& value) const {
    if (node == nullptr) {
        return false;
    } else if (value == node->data) {
        return true;
    } else if (value <= node->data) {
        return search(node->left, value);
    } else {
        return search(node->right, value);
    }
}

template <typename T>
void BinarySearchTree<T>::delete_tree(Node* node) {
    if (node != nullptr) {
        delete_tree(node->left);
        delete_tree(node->right);
        delete node;
    }
}

}  // namespace binary_search_tree
